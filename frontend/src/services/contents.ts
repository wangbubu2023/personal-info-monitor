import api, { ensureApiKey, getApiBaseURL } from './api'
import type { Content, PaginatedResponse } from '../types'

export interface ListContentsParams {
  page?: number
  page_size?: number
  source_id?: string
  source_type?: string
  read_status?: boolean
  favorited?: boolean
  archived?: boolean
  date_from?: string
  date_to?: string
  search?: string
}

export interface ContentUpdate {
  read_status?: boolean
  favorited?: boolean
  archived?: boolean
  is_user_edited?: boolean
  title?: string
  summary?: string
  full_content?: string
}

export type ReaderBlock =
  | { type: 'paragraph'; text: string }
  | { type: 'heading'; text: string; level?: 1 | 2 | 3 | 4 }
  | { type: 'image'; src: string; alt?: string; caption?: string }
  | { type: 'quote'; text: string }
  | { type: 'code'; text: string; language?: string }
  | { type: 'footnote'; marker?: string; text: string }
  | { type: 'link'; text: string; href: string }

export interface ReaderPayload {
  id: string
  source_id: string
  source_name: string
  title: string
  translated_title?: string
  original_url: string
  publish_time?: string
  read_status?: boolean
  favorited?: boolean
  body_raw: string
  body_zh: string
  translation_requested?: boolean
  translation_cached?: boolean
  has_translation_cache?: boolean
  body_translation_source?: string
  body_translation_is_summary?: boolean
  blocks?: ReaderBlock[]
  clean_html: string
}

export interface ReaderTranslateStreamInit {
  type: 'init'
  id: string
  title: string
  source_name: string
  original_url: string
  publish_time?: string | null
  paragraphs_total: number
}

export interface ReaderTranslateStreamChunk {
  type: 'chunk'
  index: number
  text: string
  translated: boolean
}

export interface ReaderTranslateStreamDone {
  type: 'done'
  paragraphs_total: number
  paragraphs_streamed: number
  translated: boolean
  translation_cached: boolean
  translated_count?: number
  partial_fallback?: boolean
  ratio?: number
  message?: string
}

export type ReaderTranslateStreamEvent =
  | ReaderTranslateStreamInit
  | ReaderTranslateStreamChunk
  | ReaderTranslateStreamDone

function downloadMarkdownBlob(data: BlobPart, filenameHint: string): void {
  const blob = new Blob([data], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${filenameHint.replace(/[\\/:*?"<>|]+/g, '').slice(0, 80) || 'content'}.md`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function buildStreamURL(path: string): string {
  const base = (getApiBaseURL() || '/api').replace(/\/+$/, '')
  if (base.startsWith('http://') || base.startsWith('https://')) {
    return `${base}${path}`
  }
  return `${window.location.origin}${base}${path}`
}

export const contentsApi = {
  // List contents
  list: async (params?: ListContentsParams): Promise<PaginatedResponse<Content>> => {
    const response = await api.get('/contents', { params })
    return response.data
  },

  // Get single content
  get: async (id: string): Promise<Content> => {
    const response = await api.get(`/contents/${id}`)
    return response.data
  },

  // Get reader payload (translation is on-demand)
  getReader: async (id: string, opts?: { translate?: boolean }): Promise<ReaderPayload> => {
    const shouldTranslate = Boolean(opts?.translate)
    const response = await api.get(`/contents/${id}/reader`, {
      params: { translate: shouldTranslate },
      timeout: shouldTranslate ? 120000 : 30000,
    })
    return response.data
  },

  // Stream translated reader body paragraph-by-paragraph (NDJSON)
  streamReaderTranslation: async (
    id: string,
    opts: {
      signal?: AbortSignal
      onEvent: (event: ReaderTranslateStreamEvent) => void
    }
  ): Promise<void> => {
    const apiKey = await ensureApiKey()
    const url = buildStreamURL(`/contents/${id}/reader/translate-stream`)
    const response = await fetch(url, {
      method: 'GET',
      headers: apiKey ? { 'X-API-Key': apiKey } : {},
      signal: opts.signal,
    })

    if (!response.ok) {
      const text = await response.text()
      throw new Error(text || `HTTP ${response.status}`)
    }
    if (!response.body) {
      throw new Error('翻译流不可用')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    for (;;) {
      const { done, value } = await reader.read()
      if (done) {
        break
      }
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const rawLine of lines) {
        const line = rawLine.trim()
        if (!line) {
          continue
        }
        try {
          const event = JSON.parse(line) as ReaderTranslateStreamEvent
          opts.onEvent(event)
        } catch {
          // ignore malformed line
        }
      }
    }

    const tail = buffer.trim()
    if (tail) {
      try {
        const event = JSON.parse(tail) as ReaderTranslateStreamEvent
        opts.onEvent(event)
      } catch {
        // ignore malformed line
      }
    }
  },

  // Update content
  update: async (id: string, data: ContentUpdate): Promise<Content> => {
    const response = await api.patch(`/contents/${id}`, data)
    return response.data
  },

  /** Set favorite explicitly (idempotent). Pass desired state after reading current item. */
  setFavorite: async (id: string, favorited: boolean): Promise<{ favorited: boolean }> => {
    const response = await api.patch(`/contents/${id}/favorite`, { favorited })
    return response.data
  },

  // Download a single content item as Markdown.
  downloadMarkdown: async (id: string, filenameHint?: string): Promise<void> => {
    const response = await api.get(`/contents/${id}/export-md`, { responseType: 'blob' })
    downloadMarkdownBlob(response.data, filenameHint || id)
  },

  // Download an event-like duplicate group as Markdown.
  downloadEventMarkdown: async (eventKey: string, filenameHint?: string): Promise<void> => {
    const response = await api.get('/contents/events/export-md', {
      params: { event_key: eventKey },
      responseType: 'blob',
    })
    downloadMarkdownBlob(response.data, filenameHint || eventKey)
  },

  // Delete content
  delete: async (id: string): Promise<void> => {
    await api.delete(`/contents/${id}`)
  },
}
