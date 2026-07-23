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

  it('never writes a long-lived api key to WebStorage', async () => {
    await writeApiKey(' secret-key ')

    expect(sessionStorageRef.getItem('pim_api_key_session')).toBeNull()
    expect(localStorageRef.getItem('pim_api_key')).toBeNull()
    expect(localStorageRef.getItem('pim_api_key_persist')).toBeNull()
    await expect(readApiKey()).resolves.toBeNull()
  })

  it('ignores remember=true in Web mode', async () => {
    await writeApiKey(' remembered ', { remember: true })

    expect(localStorageRef.getItem('pim_api_key')).toBeNull()
    expect(localStorageRef.getItem('pim_api_key_persist')).toBeNull()
    expect(sessionStorageRef.getItem('pim_api_key_session')).toBeNull()
  })

  it('scrubs pre-M0 WebStorage copies instead of re-hydrating them', async () => {
    localStorageRef.setItem('pim_api_key', 'persisted-key')
    localStorageRef.setItem('pim_api_key_persist', '1')
    sessionStorageRef.setItem('pim_api_key_session', 'session-key')

    await expect(readApiKey()).resolves.toBeNull()
    expect(sessionStorageRef.getItem('pim_api_key_session')).toBeNull()
    expect(localStorageRef.getItem('pim_api_key')).toBeNull()
    expect(localStorageRef.getItem('pim_api_key_persist')).toBeNull()
  })

  it('clears all browser-side copies of the api key', async () => {
    await writeApiKey('clear-me', { remember: true })
    await clearApiKey()

    expect(localStorageRef.getItem('pim_api_key')).toBeNull()
    expect(localStorageRef.getItem('pim_api_key_persist')).toBeNull()
    expect(sessionStorageRef.getItem('pim_api_key_session')).toBeNull()
  })

  it('rejects a legacy meta/query token and scrubs both ingress paths', async () => {
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
        location: { href: 'http://localhost:3000/?bootstrap_token=from-url' },
        history: { replaceState: (_state: unknown, _title: string, url: string) => { replacedUrl = url } },
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

    let replacedUrl: string | null = null
    await expect(readBootstrapToken()).resolves.toBeNull()
    expect(removed).toHaveLength(1)
    expect(removed[0]).toBe(metaElement)
    expect(replacedUrl).not.toContain('bootstrap_token=')
  })

  it('rejects a legacy URL query token', async () => {
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

    await expect(readBootstrapToken()).resolves.toBeNull()
  })

  it('reads a one-time bootstrap code from the URL fragment and strips it from history', async () => {
    let replacedUrl: string | null = null
    Object.defineProperty(globalThis, 'window', {
      value: {
        localStorage: localStorageRef,
        sessionStorage: sessionStorageRef,
        location: { href: 'http://localhost:3000/?keep=1#bootstrap_code=shiny-code' },
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

    await expect(readBootstrapToken()).resolves.toBe('shiny-code')
    expect(replacedUrl).not.toBeNull()
    expect(replacedUrl as unknown as string).not.toContain('bootstrap_code=')
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
