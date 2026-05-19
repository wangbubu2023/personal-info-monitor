/** Normalize user-entered source URLs (prepend https:// when scheme omitted). */
export function normalizeSourceUrl(raw: string | undefined | null): string {
  const s = (raw ?? '').trim()
  if (!s) return ''
  if (!/^https?:\/\//i.test(s)) return `https://${s}`
  return s
}

const INVALID_URL_MESSAGE = 'URL 格式无法解析，请检查地址是否正确'

/** Returns null when the input cannot be parsed as an http(s) URL with a host. */
export function parseSourceUrlInput(raw: string | undefined | null): string | null {
  const normalized = normalizeSourceUrl(raw)
  if (!normalized) return null
  try {
    const host = new URL(normalized).hostname
    if (!host) return null
    return normalized
  } catch {
    return null
  }
}

export function validateSourceUrlInput(raw: string | undefined | null): string | true {
  if (!(raw ?? '').trim()) return true
  return parseSourceUrlInput(raw) ? true : INVALID_URL_MESSAGE
}
