import axios from 'axios'
import { promptApiKey } from '../components/ui/ApiKeyModal'
import { clearApiKey, readApiKey, writeApiKey } from './apiKeyStore'

declare global {
  interface Window {
    __PIM_API_KEY_PROMPT_PROMISE__?: Promise<string | null> | null
    __PIM_API_KEY_RECOVERY_PROMISE__?: Promise<string | null> | null
  }
}

export function normalizeApiBaseURL(raw?: string | null): string {
  const value = (raw || '').trim()
  if (!value) {
    return '/api'
  }
  if (value === '/api' || value.endsWith('/api')) {
    return value
  }
  return `${value.replace(/\/+$/, '')}/api`
}

/** Tauri 打包后无 Vite 代理，直连本机 API */
function apiBaseURL(): string {
  if (import.meta.env.VITE_API_URL) {
    return normalizeApiBaseURL(import.meta.env.VITE_API_URL as string)
  }
  if (import.meta.env.TAURI_ENV_PLATFORM) {
    return 'http://127.0.0.1:8000/api'
  }
  return '/api'
}

export function getApiBaseURL(): string {
  return apiBaseURL()
}

const api = axios.create({
  baseURL: apiBaseURL(),
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

function getPromptPromise(): Promise<string | null> | null {
  return typeof window !== 'undefined' ? (window.__PIM_API_KEY_PROMPT_PROMISE__ ?? null) : null
}

function setPromptPromise(value: Promise<string | null> | null): void {
  if (typeof window !== 'undefined') {
    window.__PIM_API_KEY_PROMPT_PROMISE__ = value
  }
}

function getRecoveryPromise(): Promise<string | null> | null {
  return typeof window !== 'undefined' ? (window.__PIM_API_KEY_RECOVERY_PROMISE__ ?? null) : null
}

function setRecoveryPromise(value: Promise<string | null> | null): void {
  if (typeof window !== 'undefined') {
    window.__PIM_API_KEY_RECOVERY_PROMISE__ = value
  }
}

function normalizeApiKey(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null
  }
  const trimmed = value.trim()
  return trimmed || null
}

function getHeaderApiKey(headers: unknown): string | null {
  if (!headers || typeof headers !== 'object') {
    return null
  }

  const candidate = headers as {
    get?: (name: string) => unknown
    ['X-API-Key']?: unknown
    ['x-api-key']?: unknown
  }

  if (typeof candidate.get === 'function') {
    return normalizeApiKey(candidate.get('X-API-Key') ?? candidate.get('x-api-key'))
  }

  return normalizeApiKey(candidate['X-API-Key'] ?? candidate['x-api-key'])
}

function withApiKeyHeader<T extends { headers?: unknown }>(config: T, apiKey: string): T {
  const headers = config.headers as { set?: (name: string, value: string) => void } | undefined
  if (headers && typeof headers.set === 'function') {
    headers.set('X-API-Key', apiKey)
    return config
  }

  return {
    ...config,
    headers: {
      ...(typeof config.headers === 'object' && config.headers ? config.headers : {}),
      'X-API-Key': apiKey,
    },
  }
}

function requestApiKeyOnce(): Promise<string | null> {
  const activePrompt = getPromptPromise()
  if (activePrompt) {
    return activePrompt
  }

  const promptPromise = (async () => {
    const key = await promptApiKey()
    const trimmed = (key || '').trim()
    if (!trimmed) {
      return null
    }
    return writeApiKey(trimmed).then(() => trimmed)
  })().finally(() => {
    setPromptPromise(null)
  })

  setPromptPromise(promptPromise)
  return promptPromise
}

export async function ensureApiKey(): Promise<string | null> {
  const existing = await readApiKey()
  if (existing && existing.trim()) {
    return existing.trim()
  }
  return requestApiKeyOnce()
}

async function recoverApiKey(failedApiKey: string | null): Promise<string | null> {
  const currentApiKey = await readApiKey()
  if (currentApiKey && currentApiKey !== failedApiKey) {
    return currentApiKey
  }

  const activeRecovery = getRecoveryPromise()
  if (activeRecovery) {
    return activeRecovery
  }

  const recoveryPromise = (async () => {
    const latestApiKey = await readApiKey()
    if (latestApiKey && latestApiKey !== failedApiKey) {
      return latestApiKey
    }

    if (latestApiKey && failedApiKey && latestApiKey === failedApiKey) {
      await clearApiKey()
    }

    return requestApiKeyOnce()
  })().finally(() => {
    setRecoveryPromise(null)
  })

  setRecoveryPromise(recoveryPromise)
  return recoveryPromise
}

// Request interceptor
api.interceptors.request.use(
  async (config) => {
    // Prompt once up front so the first page load doesn't fan out into 401 retries.
    const apiKey = await ensureApiKey()
    if (apiKey) {
      return withApiKeyHeader(config, apiKey)
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor
api.interceptors.response.use(
  (response) => {
    return response
  },
  async (error) => {
    const originalConfig = error.config as (typeof error.config & { _retry?: boolean }) | undefined
    if (error.response?.status === 401 && !originalConfig?._retry) {
      // Coordinate 401 recovery so parallel requests only prompt once.
      const failedApiKey = getHeaderApiKey(originalConfig?.headers)
      const key = await recoverApiKey(failedApiKey)
      if (key && originalConfig) {
        originalConfig._retry = true
        return api.request(withApiKeyHeader(originalConfig, key))
      }
    }
    return Promise.reject(error)
  }
)

export default api
