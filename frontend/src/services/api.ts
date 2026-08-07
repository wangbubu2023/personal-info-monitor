import axios, {
  AxiosError,
  AxiosHeaders,
  type AxiosAdapter,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'
import {
  promptApiKey,
  showBootstrapNotice,
  type BootstrapNoticeReason,
} from '../components/ui/ApiKeyModal'
import { clearApiKey, hasStoredCredential, isTauriRuntime, readBootstrapToken, writeApiKey } from './apiKeyStore'

declare global {
  interface Window {
    __PIM_API_KEY_PROMPT_PROMISE__?: Promise<string | null> | null
    __PIM_API_KEY_RECOVERY_PROMISE__?: Promise<string | null> | null
    __PIM_WEB_SESSION_PROMISE__?: Promise<boolean> | null
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
  withCredentials: true,
})

interface TauriProxyResponse {
  status: number
  content_type?: string | null
  body: string
}

async function invokeTauriApi(method: string, path: string, body?: string): Promise<TauriProxyResponse> {
  const { invoke } = await import('@tauri-apps/api/core')
  return invoke<TauriProxyResponse>('api_request', {
    request: { method, path, body: body ?? null },
  })
}

function tauriRequestPath(config: InternalAxiosRequestConfig): string {
  const resolved = new URL(axios.getUri(config), 'http://pim.local')
  return `${resolved.pathname}${resolved.search}`
}

function tauriResponseData(response: TauriProxyResponse, responseType?: string): unknown {
  if (responseType === 'text') return response.body
  if (responseType === 'blob') {
    return new Blob([response.body], { type: response.content_type || 'application/octet-stream' })
  }
  if (responseType === 'arraybuffer') return new TextEncoder().encode(response.body).buffer
  try {
    return JSON.parse(response.body)
  } catch {
    return response.body
  }
}

const tauriAdapter: AxiosAdapter = async (config) => {
  let requestBody: string | undefined
  if (typeof config.data === 'string') requestBody = config.data
  else if (config.data !== undefined && config.data !== null) requestBody = JSON.stringify(config.data)

  const proxied = await invokeTauriApi(
    String(config.method || 'GET').toUpperCase(),
    tauriRequestPath(config),
    requestBody,
  )
  const headers = new AxiosHeaders()
  if (proxied.content_type) headers.set('Content-Type', proxied.content_type)
  const response: AxiosResponse = {
    data: tauriResponseData(proxied, config.responseType),
    status: proxied.status,
    statusText: String(proxied.status),
    headers,
    config,
    request: null,
  }
  if (!config.validateStatus || config.validateStatus(response.status)) return response
  throw new AxiosError(
    `Request failed with status code ${response.status}`,
    response.status >= 500 ? AxiosError.ERR_BAD_RESPONSE : AxiosError.ERR_BAD_REQUEST,
    config,
    null,
    response,
  )
}

export async function tauriApiRequestRaw(method: string, path: string, signal?: AbortSignal): Promise<TauriProxyResponse> {
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
  const response = await invokeTauriApi(method, path)
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
  return response
}

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

function readCsrfCookie(): string | null {
  if (typeof document === 'undefined') return null
  const match = document.cookie.split(';').map(part => part.trim()).find(part => part.startsWith('pim_csrf='))
  return match ? decodeURIComponent(match.slice('pim_csrf='.length)) : null
}

function setRecoveryPromise(value: Promise<string | null> | null): void {
  if (typeof window !== 'undefined') {
    window.__PIM_API_KEY_RECOVERY_PROMISE__ = value
  }
}

// Resolve the backend origin for Web session bootstrap requests.
//
// Production (FastAPI serves the SPA): the frontend is on the same origin as the
// backend, so a relative path is correct and avoids any CORS issue regardless of
// whether the user typed "localhost" or "127.0.0.1" in the address bar.
//
// Dev uses the same-origin Vite /bootstrap proxy so SameSite=Strict cookies
// remain valid and the one-time code never crosses origins.
//
// Tauri: always direct loopback.
function backendOrigin(): string {
  const viteApiUrl = (import.meta.env.VITE_API_URL as string | undefined) || ''
  if (viteApiUrl) {
    // Explicit override (e.g. custom dev backend) — strip /api suffix.
    return viteApiUrl.replace(/\/api\/?$/, '').replace(/\/$/, '')
  }
  if (import.meta.env.TAURI_ENV_PLATFORM) {
    return 'http://127.0.0.1:8000'
  }
  if (import.meta.env.DEV) {
    return ''
  }
  // Production: FastAPI serves this file, so we're on the same origin.
  return ''
}

/** Establish an HttpOnly Web session without exposing a long-lived key. */
let webSessionEstablished = false
let webSessionBlocked = false

type WebSessionProbe = 'authenticated' | 'missing' | 'unavailable'

async function probeWebSession(): Promise<WebSessionProbe> {
  try {
    const response = await fetch(`${backendOrigin()}/bootstrap/session`, {
      credentials: 'include',
      signal: AbortSignal.timeout(3000),
    })
    if (response.ok) {
      webSessionEstablished = true
      return 'authenticated'
    }
    webSessionEstablished = false
    return response.status === 401 ? 'missing' : 'unavailable'
  } catch {
    webSessionEstablished = false
    return 'unavailable'
  }
}

type BootstrapExchangeResult =
  | { ok: true }
  | { ok: false; reason: BootstrapNoticeReason }

async function exchangeBootstrapCode(code: string): Promise<BootstrapExchangeResult> {
  try {
    const resp = await fetch(`${backendOrigin()}/bootstrap/exchange`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
      signal: AbortSignal.timeout(3000),
    })
    if (resp.ok) return { ok: true }
    webSessionEstablished = false
    if (resp.status === 403) return { ok: false, reason: 'origin_not_allowed' }
    if (resp.status === 401) return { ok: false, reason: 'invalid_or_expired' }
    return { ok: false, reason: 'unavailable' }
  } catch {
    webSessionEstablished = false
    return { ok: false, reason: 'unavailable' }
  }
}

function blockWebSession(reason: BootstrapNoticeReason): false {
  if (!webSessionBlocked) {
    webSessionBlocked = true
    showBootstrapNotice(reason)
  }
  return false
}

async function ensureWebSession(): Promise<boolean> {
  if (webSessionEstablished) return true
  if (webSessionBlocked) return false
  const active = typeof window !== 'undefined' ? window.__PIM_WEB_SESSION_PROMISE__ : null
  if (active) return active
  const promise = (async () => {
    const initialProbe = await probeWebSession()
    if (initialProbe === 'authenticated') return true
    const codeFromFragment = await readBootstrapToken()
    if (!codeFromFragment) {
      return blockWebSession(initialProbe === 'unavailable' ? 'unavailable' : 'required')
    }

    const exchanged = await exchangeBootstrapCode(codeFromFragment)
    if (!exchanged.ok) return blockWebSession(exchanged.reason)

    const verification = await probeWebSession()
    if (verification === 'authenticated') return true
    return blockWebSession(
      verification === 'unavailable' ? 'unavailable' : 'cookie_not_persisted',
    )
  })().finally(() => {
    if (typeof window !== 'undefined') window.__PIM_WEB_SESSION_PROMISE__ = null
  })
  if (typeof window !== 'undefined') window.__PIM_WEB_SESSION_PROMISE__ = promise
  return promise
}

function requestApiKeyOnce(): Promise<string | null> {
  const activePrompt = getPromptPromise()
  if (activePrompt) {
    return activePrompt
  }

  const promptPromise = (async () => {
    const { apiKey, remember } = await promptApiKey()
    const trimmed = (apiKey || '').trim()
    if (!trimmed) {
      return null
    }
    return writeApiKey(trimmed, { remember }).then(() => trimmed)
  })().finally(() => {
    setPromptPromise(null)
  })

  setPromptPromise(promptPromise)
  return promptPromise
}

export async function ensureApiKey(): Promise<string | null> {
  if (!isTauriRuntime()) {
    if (!await ensureWebSession()) {
      throw new Error('PIM Web session is not established')
    }
    return null
  }
  if (await hasStoredCredential()) return null
  // User-entered material is sent directly to the Rust keychain command and
  // is never returned to an HTTP interceptor.
  await requestApiKeyOnce()
  return null
}

async function recoverApiKey(): Promise<string | null> {
  if (!isTauriRuntime()) {
    webSessionEstablished = false
    if (webSessionBlocked) return null
    const activeRecovery = getRecoveryPromise()
    if (activeRecovery) return activeRecovery
    const recoveryPromise = (async () => {
      await ensureWebSession()
      return null
    })().finally(() => setRecoveryPromise(null))
    setRecoveryPromise(recoveryPromise)
    return recoveryPromise
  }
  const activeRecovery = getRecoveryPromise()
  if (activeRecovery) {
    return activeRecovery
  }

  const recoveryPromise = (async () => {
    await clearApiKey()
    await requestApiKeyOnce()
    return null
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
    if (isTauriRuntime()) {
      await ensureApiKey()
      config.headers.delete?.('X-API-Key')
      config.adapter = tauriAdapter
      return config
    }
    await ensureApiKey()
    const method = String(config.method || 'get').toUpperCase()
    const csrf = readCsrfCookie()
    if (csrf && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      config.headers.set?.('X-PIM-CSRF', csrf)
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
      await recoverApiKey()
      if (isTauriRuntime() && originalConfig && await hasStoredCredential()) {
        originalConfig._retry = true
        return api.request(originalConfig)
      }
      if (!isTauriRuntime() && webSessionEstablished && originalConfig) {
        originalConfig._retry = true
        return api.request(originalConfig)
      }
    }
    return Promise.reject(error)
  }
)

export default api
