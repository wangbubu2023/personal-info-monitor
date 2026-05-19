import { beforeEach, describe, expect, it } from 'vitest'
import { clearApiKey, readApiKey, readBootstrapToken, writeApiKey } from './apiKeyStore'

class MemoryStorage implements Storage {
  private values = new Map<string, string>()

  get length(): number {
    return this.values.size
  }

  clear(): void {
    this.values.clear()
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null
  }

  key(index: number): string | null {
    return Array.from(this.values.keys())[index] ?? null
  }

  removeItem(key: string): void {
    this.values.delete(key)
  }

  setItem(key: string, value: string): void {
    this.values.set(key, String(value))
  }
}

describe('apiKeyStore', () => {
  const localStorageRef = new MemoryStorage()
  const sessionStorageRef = new MemoryStorage()

  beforeEach(() => {
    localStorageRef.clear()
    sessionStorageRef.clear()
    Object.defineProperty(globalThis, 'window', {
      value: {
        localStorage: localStorageRef,
        sessionStorage: sessionStorageRef,
      },
      configurable: true,
      writable: true,
    })
  })

  it('defaults to session-scoped storage only (no localStorage persistence)', async () => {
    await writeApiKey(' secret-key ')

    expect(sessionStorageRef.getItem('pim_api_key_session')).toBe('secret-key')
    expect(localStorageRef.getItem('pim_api_key')).toBeNull()
    expect(localStorageRef.getItem('pim_api_key_persist')).toBeNull()
    await expect(readApiKey()).resolves.toBe('secret-key')
  })

  it('persists to localStorage only when remember=true is explicit', async () => {
    await writeApiKey(' remembered ', { remember: true })

    expect(localStorageRef.getItem('pim_api_key')).toBe('remembered')
    expect(localStorageRef.getItem('pim_api_key_persist')).toBe('1')
    expect(sessionStorageRef.getItem('pim_api_key_session')).toBe('remembered')
  })

  it('re-hydrates from localStorage when the remember flag is set', async () => {
    localStorageRef.setItem('pim_api_key', 'persisted-key')
    localStorageRef.setItem('pim_api_key_persist', '1')

    await expect(readApiKey()).resolves.toBe('persisted-key')
    expect(sessionStorageRef.getItem('pim_api_key_session')).toBe('persisted-key')
  })

  it('downgrades legacy localStorage entries without the remember flag to session-only', async () => {
    localStorageRef.setItem('pim_api_key', 'legacy-unflagged')

    await expect(readApiKey()).resolves.toBe('legacy-unflagged')
    expect(sessionStorageRef.getItem('pim_api_key_session')).toBe('legacy-unflagged')
    expect(localStorageRef.getItem('pim_api_key')).toBeNull()
  })

  it('clears all browser-side copies of the api key', async () => {
    await writeApiKey('clear-me', { remember: true })
    await clearApiKey()

    expect(localStorageRef.getItem('pim_api_key')).toBeNull()
    expect(localStorageRef.getItem('pim_api_key_persist')).toBeNull()
    expect(sessionStorageRef.getItem('pim_api_key_session')).toBeNull()
  })

  it('reads bootstrap token from a <meta> tag injected by the backend and removes it', async () => {
    const removed: HTMLElement[] = []
    const metaElement: any = {
      content: '  baked-in-token  ',
      parentElement: {
        removeChild: (node: HTMLElement) => {
          removed.push(node)
        },
      },
    }
    Object.defineProperty(globalThis, 'window', {
      value: {
        localStorage: localStorageRef,
        sessionStorage: sessionStorageRef,
        // Should not be consulted when meta tag already provides the token.
        location: { href: 'http://localhost:3000/?bootstrap_token=from-url' },
        history: { replaceState: () => undefined },
      },
      configurable: true,
      writable: true,
    })
    Object.defineProperty(globalThis, 'document', {
      value: {
        title: 'test',
        querySelector: (selector: string) =>
          selector === 'meta[name="pim-bootstrap-token"]' ? metaElement : null,
      },
      configurable: true,
      writable: true,
    })

    await expect(readBootstrapToken()).resolves.toBe('baked-in-token')
    expect(removed).toHaveLength(1)
    expect(removed[0]).toBe(metaElement)
  })

  it('falls back to URL query when meta tag is absent', async () => {
    Object.defineProperty(globalThis, 'document', {
      value: {
        title: 'test',
        querySelector: () => null,
      },
      configurable: true,
      writable: true,
    })
    Object.defineProperty(globalThis, 'window', {
      value: {
        localStorage: localStorageRef,
        sessionStorage: sessionStorageRef,
        location: { href: 'http://localhost:3000/?bootstrap_token=fallback-token' },
        history: { replaceState: () => undefined },
      },
      configurable: true,
      writable: true,
    })

    await expect(readBootstrapToken()).resolves.toBe('fallback-token')
  })

  it('reads bootstrap token from URL query and strips it from history', async () => {
    let replacedUrl: string | null = null
    Object.defineProperty(globalThis, 'window', {
      value: {
        localStorage: localStorageRef,
        sessionStorage: sessionStorageRef,
        location: { href: 'http://localhost:3000/?bootstrap_token=shiny-token&keep=1' },
        history: {
          replaceState: (_state: unknown, _title: string, url: string) => {
            replacedUrl = url
          },
        },
      },
      configurable: true,
      writable: true,
    })
    Object.defineProperty(globalThis, 'document', {
      value: { title: 'test' },
      configurable: true,
      writable: true,
    })

    await expect(readBootstrapToken()).resolves.toBe('shiny-token')
    expect(replacedUrl).not.toBeNull()
    expect(replacedUrl as unknown as string).not.toContain('bootstrap_token=')
    expect(replacedUrl as unknown as string).toContain('keep=1')
  })

  it('returns null when no bootstrap token is present', async () => {
    Object.defineProperty(globalThis, 'window', {
      value: {
        localStorage: localStorageRef,
        sessionStorage: sessionStorageRef,
        location: { href: 'http://localhost:3000/' },
        history: { replaceState: () => undefined },
      },
      configurable: true,
      writable: true,
    })

    await expect(readBootstrapToken()).resolves.toBeNull()
  })
})
