import type { KeywordMatchScope, MatchType } from '../../../types'

export const matchScopeLabels: Record<KeywordMatchScope, string> = {
  title: '标题',
  content: '正文',
  title_content: '标题 + 正文',
}

export const matchTypeLabels: Record<MatchType, string> = {
  exact: '精确匹配',
  contains: '包含',
  regex: '正则表达式',
}

/** 关键词在列表/摘要中的标签色（固定色卡，与后端 #RRGGBB 校验一致）。 */
export const KEYWORD_LABEL_COLORS = [
  '#ff4d4f',
  '#1677ff',
  '#52c41a',
  '#fa8c16',
  '#722ed1',
  '#13c2c2',
  '#eb2f96',
  '#faad14',
] as const

export type KeywordLabelColor = (typeof KEYWORD_LABEL_COLORS)[number]

export function isKeywordLabelColor(value: string): value is KeywordLabelColor {
  return (KEYWORD_LABEL_COLORS as readonly string[]).includes(value)
}
