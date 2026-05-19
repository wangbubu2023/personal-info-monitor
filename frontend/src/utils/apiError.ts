/** FastAPI / axios error bodies often use `detail` as string or validation array. */

type ValidationErrorItem = {
  loc?: (string | number)[]
  msg?: string
  type?: string
}

const VALIDATION_MSG_RULES: Array<{ match: (text: string) => boolean; message: string }> = [
  {
    match: (t) => /URL must include a valid host/i.test(t),
    message: 'URL 格式无法解析，请检查地址是否正确',
  },
  {
    match: (t) => /URL must start with http:\/\//i.test(t),
    message: 'URL 格式无法解析，请补全地址（可省略 https://）',
  },
  { match: (t) => /^URL is required/i.test(t), message: '请输入 URL' },
  {
    match: (t) => /Each extra URL must include a valid host/i.test(t),
    message: '附加 URL 格式无法解析，请逐行检查',
  },
]

function localizeValidationMessage(msg: string): string {
  const text = msg.trim().replace(/^Value error,\s*/i, '')
  for (const rule of VALIDATION_MSG_RULES) {
    if (rule.match(text)) return rule.message
  }
  return text
}

function formatFieldLoc(loc?: (string | number)[]): string {
  if (!loc?.length) return ''
  const tail = String(loc[loc.length - 1])
  if (tail === 'url') return 'URL'
  if (tail === 'extra_urls') return '附加 URL'
  if (tail === 'name') return '名称'
  if (tail === 'type') return '类型'
  return tail
}

function formatValidationItem(item: unknown): string {
  if (typeof item === 'string') return localizeValidationMessage(item)
  if (!item || typeof item !== 'object') return ''
  const { loc, msg } = item as ValidationErrorItem
  const field = formatFieldLoc(loc)
  const text =
    typeof msg === 'string' ? localizeValidationMessage(msg) : ''
  if (field && text) return `${field}：${text}`
  return text || field
}

/** Turn FastAPI `detail` (string | object | array) into user-facing text. */
export function formatApiErrorDetail(detail: unknown, fallback = '请求失败'): string {
  if (detail == null || detail === '') return fallback
  if (typeof detail === 'string') {
    const text = localizeValidationMessage(detail.trim())
    return text || fallback
  }
  if (Array.isArray(detail)) {
    const parts = detail.map(formatValidationItem).filter(Boolean)
    return parts.length > 0 ? parts.join('；') : fallback
  }
  if (typeof detail === 'object') {
    const obj = detail as Record<string, unknown>
    if (typeof obj.msg === 'string') {
      return localizeValidationMessage(obj.msg) || fallback
    }
    if (typeof obj.message === 'string') {
      return obj.message.trim() || fallback
    }
  }
  return fallback
}

export function getAxiosErrorMessage(error: unknown, fallback: string): string {
  if (!error || typeof error !== 'object') return fallback
  const code = (error as { code?: string }).code
  if (code === 'ECONNABORTED') {
    return '请求超时。请刷新信源列表确认是否已创建成功，避免重复添加。'
  }
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })
    .response
  if (response?.status === 409 && response.data?.detail !== undefined) {
    return formatApiErrorDetail(response.data.detail, '已存在相同类型和 URL 的监控源')
  }
  if (response?.data?.detail !== undefined) {
    return formatApiErrorDetail(response.data.detail, fallback)
  }
  const message = (error as { message?: string }).message
  if (typeof message === 'string' && message.trim()) {
    return message.trim()
  }
  return fallback
}

export function isAxiosTimeout(error: unknown): boolean {
  return Boolean(error && typeof error === 'object' && (error as { code?: string }).code === 'ECONNABORTED')
}

export function isDuplicateSourceError(error: unknown): boolean {
  return (
    Boolean(error && typeof error === 'object') &&
    (error as { response?: { status?: number } }).response?.status === 409
  )
}
