import { beforeEach, describe, expect, it } from 'vitest'
import { clearApiKey, readApiKey, writeApiKey } from './apiKeyStore'

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

  it('persists api keys across reloads in localStorage', async () => {
    await writeApiKey(' secret-key ')

    expect(localStorageRef.getItem('pim_api_key')).toBe('secret-key')
    expect(sessionStorageRef.getItem('pim_api_key_session')).toBe('secret-key')
    await expect(readApiKey()).resolves.toBe('secret-key')
  })

  it('migrates a session key into persistent storage', async () => {
    sessionStorageRef.setItem('pim_api_key_session', 'legacy-key')

    await expect(readApiKey()).resolves.toBe('legacy-key')
    expect(localStorageRef.getItem('pim_api_key')).toBe('legacy-key')
  })

  it('clears all browser-side copies of the api key', async () => {
    await writeApiKey('clear-me')
    await clearApiKey()

    expect(localStorageRef.getItem('pim_api_key')).toBeNull()
    expect(sessionStorageRef.getItem('pim_api_key_session')).toBeNull()
  })
})
