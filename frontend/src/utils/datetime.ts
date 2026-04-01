export function parseApiDate(value?: string | null): Date | null {
  if (!value) return null
  const text = String(value).trim()
  if (!text) return null

  // Backward compatibility: treat timezone-naive timestamps from API as UTC.
  const hasTimezone = /[zZ]$|[+-]\d{2}:\d{2}$/.test(text)
  const normalized = hasTimezone ? text : `${text}Z`
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatLocalDateTime(
  value?: string | null,
  locale: string = 'zh-CN',
  options?: Intl.DateTimeFormatOptions
): string {
  const date = parseApiDate(value)
  if (!date) return ''
  return date.toLocaleString(locale, options)
}

export function formatLocalDate(
  value?: string | null,
  locale: string = 'zh-CN',
  options?: Intl.DateTimeFormatOptions
): string {
  const date = parseApiDate(value)
  if (!date) return ''
  return date.toLocaleDateString(locale, options)
}
