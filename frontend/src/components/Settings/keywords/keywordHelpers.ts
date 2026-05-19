import type { AxiosError } from 'axios'
import { message } from 'antd'

import type { Keyword } from '../../../types'
import { KEYWORD_LABEL_COLORS, isKeywordLabelColor, type KeywordLabelColor } from './keywordConstants'

/** 与后端「忽略大小写」去重一致：同一段输入里重复的写法提示用户 */
export function warnSkippedCaseDuplicates(fieldLabel: string, skipped: string[]) {
  if (skipped.length === 0) return
  const preview = skipped.slice(0, 10).join('、')
  const more = skipped.length > 10 ? ` 等共 ${skipped.length} 项` : ''
  message.warning(`${fieldLabel}：以下与前面已保留的词仅大小写不同或重复出现，已忽略：${preview}${more}`)
}

export function normalizePaletteColor(value: unknown): KeywordLabelColor {
  if (typeof value === 'string') {
    const t = value.trim()
    if (isKeywordLabelColor(t)) {
      return t
    }
  }
  return KEYWORD_LABEL_COLORS[0]
}

export function getMutationErrorMessage(error: unknown, fallback: string): string {
  const axiosError = error as AxiosError<{ detail?: string }>
  return axiosError?.response?.data?.detail || fallback
}

/**
 * onFinish 的 values 在部分环境下会省略值为 `false` 的字段（如 Switch 关闭），
 * 导致 PATCH 未带上 `include_auto_equivalent_terms: false`，后端仍保持开启机翻。
 * 以 getFieldsValue(true) 为底，再用 onFinish 中已定义字段覆盖。
 */
export function mergeFinishWithFormStore(
  form: { getFieldsValue: (nameList?: true) => Record<string, unknown> },
  finishValues: Record<string, unknown>,
): Record<string, unknown> {
  const store = form.getFieldsValue(true)
  const merged: Record<string, unknown> = { ...store }
  for (const [k, val] of Object.entries(finishValues)) {
    if (val !== undefined) merged[k] = val
  }
  return merged
}

/**
 * 读取 Switch 等布尔字段：onFinish 常会省略值为 false 的项，仅用 merged 也会丢；
 * 优先读 form 当前值（`??` 可保留 false，不会像 `||` 那样误判）。
 */
export function pickFormBoolean(
  field: string,
  finishValues: Record<string, unknown>,
  merged: Record<string, unknown>,
  form: { getFieldValue: (name: string) => unknown },
  fallback: boolean,
): boolean {
  const v = form.getFieldValue(field) ?? finishValues[field] ?? merged[field]
  if (v === true || v === false) return v
  return fallback
}

/** 接口/缓存里偶发 0/1 或非布尔；与「关」一致则视为 false */
export function normalizeIncludeAutoEquivalent(raw: unknown): boolean {
  if (raw === false || raw === 0 || raw === '0') return false
  if (raw === true || raw === 1 || raw === '1') return true
  if (raw === 'false') return false
  if (raw === 'true') return true
  return true
}

/** 列表搜索：主词、备注描述、等价词（展示用 + 手动列表）子串匹配，忽略大小写 */
export function keywordRowMatchesSearch(record: Keyword, raw: string): boolean {
  const q = raw.trim().toLowerCase()
  if (!q) return true
  const parts: string[] = [
    record.keyword,
    record.description ?? '',
    ...(record.equivalent_terms ?? []),
    ...(record.manual_equivalent_terms ?? []),
  ]
  return parts.some((s) => s.toLowerCase().includes(q))
}
