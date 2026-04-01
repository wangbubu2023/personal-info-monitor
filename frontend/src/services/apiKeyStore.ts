const WEB_LOCAL_KEY = 'pim_api_key'
const WEB_SESSION_KEY = 'pim_api_key_session'

type ApiKeyStoreCommand = 'get_api_key' | 'set_api_key' | 'clear_api_key'

function isTauriRuntime(): boolean {
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

export async function readApiKey(): Promise<string | null> {
  if (isTauriRuntime()) {
    try {
      const value = await invokeStoreCommand<string | null>('get_api_key')
      return normalizeStoredKey(value)
    } catch {
      return null
    }
  }

  const persistentStorage = getWebStorage('localStorage')
  const sessionStorageRef = getWebStorage('sessionStorage')

  const persistentValue = normalizeStoredKey(persistentStorage?.getItem(WEB_LOCAL_KEY) ?? null)
  if (persistentValue) {
    return persistentValue
  }

  const sessionValue = normalizeStoredKey(sessionStorageRef?.getItem(WEB_SESSION_KEY) ?? null)
  if (sessionValue && persistentStorage) {
    persistentStorage.setItem(WEB_LOCAL_KEY, sessionValue)
  }
  return sessionValue
}

export async function writeApiKey(value: string): Promise<void> {
  const normalized = normalizeStoredKey(value)
  if (!normalized) {
    return
  }

  if (isTauriRuntime()) {
    await invokeStoreCommand<void>('set_api_key', { value: normalized })
    return
  }

  getWebStorage('localStorage')?.setItem(WEB_LOCAL_KEY, normalized)
  getWebStorage('sessionStorage')?.setItem(WEB_SESSION_KEY, normalized)
}

export async function clearApiKey(): Promise<void> {
  if (isTauriRuntime()) {
    await invokeStoreCommand<void>('clear_api_key')
    return
  }

  getWebStorage('localStorage')?.removeItem(WEB_LOCAL_KEY)
  getWebStorage('sessionStorage')?.removeItem(WEB_SESSION_KEY)
}
