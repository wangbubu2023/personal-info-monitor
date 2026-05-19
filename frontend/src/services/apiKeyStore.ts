/**
 * API-key / bootstrap-token storage abstraction.
 *
 * Historically this module open-coded a branch-per-function
 * ``if (isTauriRuntime()) { … } else { … }`` for every read/write, with
 * the session↔local migration logic hand-rolled each time. The 2026-04-20
 * audit (§8.2) flagged the duplication. We now define a tiny strategy
 * interface with two concrete backends — :class:`TauriKeyStorage` and
 * :class:`WebKeyStorage` — and a single :func:`activeStorage` dispatcher.
 *
 * Behaviour is unchanged:
 *  * Tauri reads/writes go through the Rust ``*_api_key`` commands which
 *    own the 0600-owned ``runtime-secrets.json``.
 *  * Web stores default to sessionStorage (XSS blast radius reduced), and
 *    only persist to localStorage when the operator explicitly opts in via
 *    ``writeApiKey(value, { remember: true })``.
 */

const WEB_LOCAL_KEY = 'pim_api_key'
const WEB_SESSION_KEY = 'pim_api_key_session'
const WEB_REMEMBER_FLAG = 'pim_api_key_persist'

type ApiKeyStoreCommand = 'get_api_key' | 'set_api_key' | 'clear_api_key' | 'get_bootstrap_token'

export interface WriteApiKeyOptions {
  /**
   * When true (and not running inside the Tauri shell) the API Key is persisted
   * to localStorage so it survives browser restarts. Default is false: we only
   * keep the key in sessionStorage so closing the tab invalidates it, which
   * reduces the blast radius of any future XSS bug.
   */
  remember?: boolean
}

export function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

async function invokeStoreCommand<T>(command: ApiKeyStoreCommand, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import('@tauri-apps/api/core')
  return invoke<T>(command, args)
}

function getWebStorage(kind: 'localStorage' | 'sessionStorage'): Storage | null {
  if (typeof window === 'undefined') {
    return null
  }
  try {
    return window[kind]
  } catch {
    return null
  }
}

function normalizeStoredKey(value: string | null): string | null {
  const trimmed = (value || '').trim()
  return trimmed || null
}

/**
 * Common interface implemented by every concrete storage backend. Kept tiny
 * on purpose — just enough to cover the flows `useApiKey`/axios interceptor
 * really call.
 */
interface KeyStorage {
  readBootstrapToken(): Promise<string | null>
  readApiKey(): Promise<string | null>
  writeApiKey(value: string, options: WriteApiKeyOptions): Promise<void>
  clearApiKey(): Promise<void>
}

class TauriKeyStorage implements KeyStorage {
  async readBootstrapToken(): Promise<string | null> {
    try {
      const value = await invokeStoreCommand<string | null>('get_bootstrap_token')
      return normalizeStoredKey(value)
    } catch {
      return null
    }
  }

  async readApiKey(): Promise<string | null> {
    try {
      const value = await invokeStoreCommand<string | null>('get_api_key')
      return normalizeStoredKey(value)
    } catch {
      return null
    }
  }

  async writeApiKey(value: string): Promise<void> {
    await invokeStoreCommand<void>('set_api_key', { value })
  }

  async clearApiKey(): Promise<void> {
    await invokeStoreCommand<void>('clear_api_key')
  }
}

class WebKeyStorage implements KeyStorage {
  async readBootstrapToken(): Promise<string | null> {
    if (typeof window === 'undefined') {
      return null
    }

    // 1) Preferred path for same-host web access: the backend stamps the token
    //    into <meta name="pim-bootstrap-token" …> when serving index.html to a
    //    loopback client. We pluck it out (and strip the tag from the DOM so it
    //    doesn't linger for other scripts to read) and hand it to the caller,
    //    which will silently exchange it for the API key via /local-token.
    try {
      if (typeof document !== 'undefined') {
        const meta = document.querySelector?.(
          'meta[name="pim-bootstrap-token"]',
        ) as HTMLMetaElement | null
        const fromMeta = (meta?.content || '').trim()
        if (fromMeta) {
          meta?.parentElement?.removeChild(meta)
          return fromMeta
        }
      }
    } catch {
      // DOM access may throw in non-browser runtimes (e.g. SSR shims). Fall through.
    }

    // 2) Legacy path kept for "share a one-shot URL" flows: Tauri and the CLI
    //    can still launch the browser with ?bootstrap_token=… and we strip it
    //    from history so it doesn't leak into analytics.
    try {
      const href = window.location?.href
      if (!href) return null
      const url = new URL(href)
      const fromQuery = (url.searchParams.get('bootstrap_token') || '').trim()
      if (fromQuery) {
        url.searchParams.delete('bootstrap_token')
        const title = typeof document !== 'undefined' ? document.title : ''
        window.history?.replaceState({}, title, url.toString())
        return fromQuery
      }
    } catch {
      // Non-standard runtime (e.g. SSR shim) — fall through.
    }
    return null
  }

  async readApiKey(): Promise<string | null> {
    const persistentStorage = getWebStorage('localStorage')
    const sessionStorageRef = getWebStorage('sessionStorage')

    // Session storage wins — reflects the most recent write and expires with the tab.
    const sessionValue = normalizeStoredKey(sessionStorageRef?.getItem(WEB_SESSION_KEY) ?? null)
    if (sessionValue) {
      return sessionValue
    }

    // Fall back to persistent storage only when the user previously opted in.
    const rememberFlag = persistentStorage?.getItem(WEB_REMEMBER_FLAG)
    if (rememberFlag === '1') {
      const persistentValue = normalizeStoredKey(persistentStorage?.getItem(WEB_LOCAL_KEY) ?? null)
      if (persistentValue) {
        sessionStorageRef?.setItem(WEB_SESSION_KEY, persistentValue)
        return persistentValue
      }
    }

    // One-shot migration: legacy clients wrote to localStorage without setting the
    // remember flag. Upgrade them to session-only on first read so the stricter
    // default applies without losing the user's key.
    const legacyPersisted = normalizeStoredKey(persistentStorage?.getItem(WEB_LOCAL_KEY) ?? null)
    if (legacyPersisted && !rememberFlag) {
      sessionStorageRef?.setItem(WEB_SESSION_KEY, legacyPersisted)
      persistentStorage?.removeItem(WEB_LOCAL_KEY)
      return legacyPersisted
    }

    return null
  }

  async writeApiKey(value: string, options: WriteApiKeyOptions = {}): Promise<void> {
    const persistentStorage = getWebStorage('localStorage')
    const sessionStorageRef = getWebStorage('sessionStorage')

    sessionStorageRef?.setItem(WEB_SESSION_KEY, value)
    if (options.remember) {
      persistentStorage?.setItem(WEB_LOCAL_KEY, value)
      persistentStorage?.setItem(WEB_REMEMBER_FLAG, '1')
    } else {
      persistentStorage?.removeItem(WEB_LOCAL_KEY)
      persistentStorage?.removeItem(WEB_REMEMBER_FLAG)
    }
  }

  async clearApiKey(): Promise<void> {
    getWebStorage('localStorage')?.removeItem(WEB_LOCAL_KEY)
    getWebStorage('localStorage')?.removeItem(WEB_REMEMBER_FLAG)
    getWebStorage('sessionStorage')?.removeItem(WEB_SESSION_KEY)
  }
}

let _cachedTauri: TauriKeyStorage | null = null
let _cachedWeb: WebKeyStorage | null = null

function activeStorage(): KeyStorage {
  if (isTauriRuntime()) {
    if (!_cachedTauri) _cachedTauri = new TauriKeyStorage()
    return _cachedTauri
  }
  if (!_cachedWeb) _cachedWeb = new WebKeyStorage()
  return _cachedWeb
}

/**
 * Read the bootstrap token used to authenticate against /local-token.
 * Tauri: reads runtime-secrets.json via a Rust command (file is 0600-owned).
 * Web:   reads a one-shot ?bootstrap_token=... query parameter and clears it
 *        from the URL so it doesn't leak into history/analytics.
 * Returns null when no source is available (user will be prompted manually).
 */
export async function readBootstrapToken(): Promise<string | null> {
  return activeStorage().readBootstrapToken()
}

export async function readApiKey(): Promise<string | null> {
  return activeStorage().readApiKey()
}

export async function writeApiKey(value: string, options: WriteApiKeyOptions = {}): Promise<void> {
  const normalized = normalizeStoredKey(value)
  if (!normalized) {
    return
  }
  await activeStorage().writeApiKey(normalized, options)
}

export async function clearApiKey(): Promise<void> {
  await activeStorage().clearApiKey()
}
