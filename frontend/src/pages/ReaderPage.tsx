import React, { useEffect, useMemo, useState } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Spin } from 'antd'
import { isAxiosError } from 'axios'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { contentsApi } from '../services/contents'

function splitForReader(text: string): string[] {
  const cleaned = (text || '').replace(/\r\n/g, '\n').trim()
  if (!cleaned) {
    return []
  }
  const paragraphs = cleaned.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean)
  if (paragraphs.length > 1) {
    return paragraphs
  }
  const protectedText = cleaned.replace(/\b(?:[A-Za-z]\.){2,}/g, (abbr) => abbr.replace(/\./g, '<DOT>'))
  return protectedText
    .split(/(?<=[。！？.!?])\s+/)
    .map((p) => p.replace(/<DOT>/g, '.').trim())
    .filter(Boolean)
}

const ReaderPage: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const [searchParams] = useSearchParams()
  const translateRequested = ['1', 'true', 'yes'].includes((searchParams.get('translate') || '').toLowerCase())
  const [streamChunks, setStreamChunks] = useState<string[]>([])
  const [streamTotal, setStreamTotal] = useState(0)
  const [streamTitle, setStreamTitle] = useState<string | null>(null)
  const [streamLoading, setStreamLoading] = useState(false)
  const [streamError, setStreamError] = useState<string | null>(null)
  const [streamHint, setStreamHint] = useState<string | null>(null)
  const [streamFinished, setStreamFinished] = useState(false)
  const [streamSucceeded, setStreamSucceeded] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['reader', id],
    queryFn: () => contentsApi.getReader(id || '', { translate: false }),
    enabled: !!id,
    retry: false,
  })

  useEffect(() => {
    setStreamChunks([])
    setStreamTotal(0)
    setStreamTitle(null)
    setStreamLoading(false)
    setStreamError(null)
    setStreamHint(null)
    setStreamFinished(false)
    setStreamSucceeded(false)

    if (!translateRequested || !id || !data) {
      return
    }

    const controller = new AbortController()
    setStreamLoading(true)
    contentsApi
      .streamReaderTranslation(id, {
        signal: controller.signal,
        onEvent: (event) => {
          if (event.type === 'init') {
            setStreamTotal(event.paragraphs_total || 0)
            if (event.title) {
              setStreamTitle(event.title)
            }
            return
          }
          if (event.type === 'chunk') {
            setStreamChunks((prev) => [...prev, event.text])
            return
          }
          if (event.type === 'done') {
            setStreamLoading(false)
            setStreamFinished(true)
            const ok = Boolean(event.translated) && !event.partial_fallback
            setStreamSucceeded(ok)
            if (!ok) {
              setStreamChunks([])
            }
            if (event.message && event.message !== 'ok') {
              setStreamHint(event.message)
            }
          }
        },
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) {
          return
        }
        setStreamLoading(false)
        setStreamFinished(true)
        setStreamSucceeded(false)
        setStreamChunks([])
        setStreamError(err instanceof Error ? err.message : '译文流加载失败')
      })

    return () => controller.abort()
  }, [translateRequested, id, data])

  const displayTitle = useMemo(() => {
    if (!data) {
      return ''
    }
    if (!translateRequested) {
      return data.title
    }
    if (streamTitle && streamTitle.trim()) {
      return streamTitle
    }
    return data.translated_title || data.title
  }, [data, translateRequested, streamTitle])

  const displayParagraphs = useMemo(() => {
    if (!data) {
      return []
    }
    if (!translateRequested) {
      return splitForReader(data.body_raw || '')
    }
    if (streamFinished && !streamSucceeded) {
      return splitForReader(data.body_raw || '')
    }
    if (streamChunks.length > 0) {
      return streamChunks
    }
    return splitForReader(data.body_zh || data.body_raw || '')
  }, [data, translateRequested, streamChunks])

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }} data-testid="reader-loading">
        <Spin size="large" />
      </div>
    )
  }

  if (!data) {
    const status = isAxiosError(error) ? error.response?.status : undefined
    return (
      <div style={{ maxWidth: 960, margin: '24px auto', padding: '0 16px', color: '#666' }} data-testid="reader-empty">
        {status === 404
          ? '内容不存在或已被删除。'
          : translateRequested
            ? '译文加载失败，请稍后重试。'
            : '内容加载失败，请稍后重试。'}
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 980, margin: '16px auto 32px', padding: '0 16px' }} data-testid="reader-page">
      <div style={{ marginBottom: 12 }}>
        <Link to="/" style={{ marginRight: 8 }}>
          <Button icon={<ArrowLeftOutlined />} size="small" data-testid="reader-back-btn">
            返回监控
          </Button>
        </Link>
        <a href={data.original_url} target="_blank" rel="noopener noreferrer">
          <Button size="small">打开原文</Button>
        </a>
        {id && !translateRequested && (
          <Link to={`/reader/${id}?translate=1`} style={{ marginLeft: 8 }}>
            <Button size="small">查看译文</Button>
          </Link>
        )}
        {id && translateRequested && (
          <Link to={`/reader/${id}`} style={{ marginLeft: 8 }}>
            <Button size="small">查看原文版</Button>
          </Link>
        )}
      </div>

      {(streamLoading || streamHint || streamError) && translateRequested && (
        <div style={{ marginBottom: 12 }}>
          {streamLoading && (
            <Alert
              type="info"
              showIcon
              message={`正在生成译文（${streamChunks.length}${streamTotal > 0 ? ` / ${streamTotal}` : ''} 段）`}
            />
          )}
          {!streamLoading && streamHint && (
            <Alert
              type="warning"
              showIcon
              message={streamHint}
            />
          )}
          {streamError && (
            <Alert
              type="error"
              showIcon
              message="译文加载失败"
              description={streamError}
            />
          )}
        </div>
      )}

      <section
        data-testid="reader-iframe"
        style={{
          border: '1px solid #d7dcc8',
          borderRadius: 12,
          background: '#fff',
          padding: '28px 24px',
          lineHeight: 1.9,
        }}
      >
        <h1 style={{ margin: 0, fontSize: 34, lineHeight: 1.4, color: '#1f1f1f' }}>{displayTitle || '未命名内容'}</h1>
        <div style={{ marginTop: 8, marginBottom: 20, color: '#6b7280', fontSize: 13 }}>
          来源：{data.source_name || '-'}
          {' | '}
          发布时间：{data.publish_time || '-'}
          {' | '}
          <a href={data.original_url} target="_blank" rel="noopener noreferrer" style={{ color: '#6b7c3f' }}>
            原文链接
          </a>
        </div>
        <article>
          {displayParagraphs.length === 0 && <p>暂无可阅读正文。</p>}
          {displayParagraphs.map((paragraph, index) => (
            <p key={`${index}-${paragraph.slice(0, 20)}`} style={{ margin: '0 0 14px', whiteSpace: 'pre-wrap' }}>
              {paragraph}
            </p>
          ))}
        </article>
      </section>
    </div>
  )
}

export default ReaderPage
