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
 * Tauri secrets stay behind the Rust keychain commands. Web authentication is
 * cookie-only: long-lived API keys are never returned from this module and
 * stale pre-M0 WebStorage/query/meta copies are actively scrubbed.
 */

type ApiKeyStoreCommand = 'has_api_key' | 'set_api_key' | 'clear_api_key'

export interface WriteApiKeyOptions {
  /** Legacy UI option. Web ignores it; Tauri always stores in OS Keychain. */
  remember?: boolean
}

export function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

async function invokeStoreCommand<T>(command: ApiKeyStoreCommand, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import('@tauri-apps/api/core')
  return invoke<T>(command, args)
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
  hasCredential(): Promise<boolean>
  writeApiKey(value: string, options: WriteApiKeyOptions): Promise<void>
  clearApiKey(): Promise<void>
}

class TauriKeyStorage implements KeyStorage {
  async readBootstrapToken(): Promise<string | null> {
    return null
  }

  async readApiKey(): Promise<string | null> {
    // The renderer is deliberately unable to retrieve the key plaintext.
    return null
  }

  async hasCredential(): Promise<boolean> {
    try {
      return await invokeStoreCommand<boolean>('has_api_key')
    } catch {
      return false
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
  private purgeLegacySecrets(): void {
    if (typeof window === 'undefined') return
    try {
      window.localStorage?.removeItem('pim_api_key')
      window.localStorage?.removeItem('pim_api_key_persist')
      window.sessionStorage?.removeItem('pim_api_key_session')
    } catch {
      // Storage may be disabled; authentication remains cookie-only.
    }
  }

  async readBootstrapToken(): Promise<string | null> {
    if (typeof window === 'undefined') {
      return null
    }

    this.purgeLegacySecrets()

    // A short-lived one-time code may arrive in the fragment. Fragments are
    // not sent to the server/Referer, and replaceState removes it before any
    // application request or analytics can observe it.
    try {
      const href = window.location?.href
      if (!href) return null
      const url = new URL(href)

      // Retired ingress paths are never trusted, but scrub them so an upgrade
      // does not leave a long-lived secret in history or the live DOM.
      const legacyMeta = typeof document !== 'undefined' && typeof document.querySelector === 'function'
        ? document.querySelector('meta[name="pim-bootstrap-token"]')
        : null
      legacyMeta?.parentElement?.removeChild(legacyMeta)
      const hadLegacyQuery = url.searchParams.has('bootstrap_token')
      if (hadLegacyQuery) url.searchParams.delete('bootstrap_token')

      const fragment = new URLSearchParams(url.hash.replace(/^#/, ''))
      const code = (fragment.get('bootstrap_code') || '').trim()
      if (code || hadLegacyQuery) {
        url.hash = ''
        const title = typeof document !== 'undefined' ? document.title : ''
        window.history?.replaceState({}, title, url.toString())
      }
      if (code) {
        return code
      }
    } catch {
      // Non-standard runtime (e.g. SSR shim) — fall through.
    }
    return null
  }

  async readApiKey(): Promise<string | null> {
    this.purgeLegacySecrets()
    return null
  }

  async hasCredential(): Promise<boolean> {
    return false
  }

  async writeApiKey(): Promise<void> {
    // Web authentication is cookie-only. Long-lived keys never enter renderer
    // storage, even when an older caller passes remember=true.
    this.purgeLegacySecrets()
  }

  async clearApiKey(): Promise<void> {
    // HttpOnly cookies are revoked by the backend logout endpoint.
    this.purgeLegacySecrets()
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
 * Read a short-lived bootstrap value. Web accepts only a one-time code in the
 * URL fragment and removes it immediately. Legacy meta/query tokens are
 * deleted but never returned.
 */
export async function readBootstrapToken(): Promise<string | null> {
  return activeStorage().readBootstrapToken()
}

export async function readApiKey(): Promise<string | null> {
  return activeStorage().readApiKey()
}

export async function hasStoredCredential(): Promise<boolean> {
  return activeStorage().hasCredential()
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
