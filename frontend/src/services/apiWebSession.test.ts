import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  readBootstrapToken: vi.fn<() => Promise<string | null>>(),
  showBootstrapNotice: vi.fn(),
}))

vi.mock('../components/ui/ApiKeyModal', () => ({
  promptApiKey: vi.fn(),
  showBootstrapNotice: mocks.showBootstrapNotice,
}))

vi.mock('./apiKeyStore', () => ({
  clearApiKey: vi.fn(),
  hasStoredCredential: vi.fn(),
  isTauriRuntime: () => false,
  readBootstrapToken: mocks.readBootstrapToken,
  writeApiKey: vi.fn(),
}))

function fetchResponse(status: number): Response {
  return { ok: status >= 200 && status < 300, status } as Response
}

describe('Web bootstrap session', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    mocks.readBootstrapToken.mockResolvedValue(null)
    window.__PIM_WEB_SESSION_PROMISE__ = null
    window.__PIM_API_KEY_RECOVERY_PROMISE__ = null
  })

  it('never asks for a code and shows the binding guidance only once', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(fetchResponse(401)))
    const { ensureApiKey } = await import('./api')

    await expect(ensureApiKey()).rejects.toThrow('Web session is not established')
    await expect(ensureApiKey()).rejects.toThrow('Web session is not established')

    expect(fetch).toHaveBeenCalledTimes(1)
    expect(mocks.showBootstrapNotice).toHaveBeenCalledOnce()
    expect(mocks.showBootstrapNotice).toHaveBeenCalledWith('required')
  })

  it('turns an origin rejection into one actionable notice', async () => {
    mocks.readBootstrapToken.mockResolvedValue('one-time-code-123456')
    vi.stubGlobal(
      'fetch',
      vi.fn()
        .mockResolvedValueOnce(fetchResponse(401))
        .mockResolvedValueOnce(fetchResponse(403)),
    )
    const { ensureApiKey } = await import('./api')

    await expect(ensureApiKey()).rejects.toThrow('Web session is not established')

    expect(fetch).toHaveBeenCalledTimes(2)
    expect(mocks.showBootstrapNotice).toHaveBeenCalledOnce()
    expect(mocks.showBootstrapNotice).toHaveBeenCalledWith('origin_not_allowed')
  })

  it('verifies the HttpOnly cookie after a successful one-click exchange', async () => {
    mocks.readBootstrapToken.mockResolvedValue('one-time-code-123456')
    vi.stubGlobal(
      'fetch',
      vi.fn()
        .mockResolvedValueOnce(fetchResponse(401))
        .mockResolvedValueOnce(fetchResponse(200))
        .mockResolvedValueOnce(fetchResponse(200)),
    )
    const { ensureApiKey } = await import('./api')

    await expect(ensureApiKey()).resolves.toBeNull()

    expect(fetch).toHaveBeenCalledTimes(3)
    expect(mocks.showBootstrapNotice).not.toHaveBeenCalled()
  })
})
