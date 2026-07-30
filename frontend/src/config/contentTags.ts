export const CONTENT_TAG_CHOICES = [
  ['domestic_politics', '国内时政'],
  ['public_safety', '公共安全'],
  ['geopolitics', '地缘外交'],
  ['macro_economy', '宏观经济'],
  ['macro_finance', '宏观金融'],
  ['markets', '市场交易'],
  ['regulation', '监管政策'],
  ['industry_news', '行业新闻'],
  ['company_news', '公司新闻'],
  ['product_news', '产品新闻'],
  ['vc_deals', '创投融资'],
  ['public_figures', '公共人物'],
  ['other', '其它'],
] as const

export type ContentTagKey = (typeof CONTENT_TAG_CHOICES)[number][0]

const CONTENT_TAG_KEYS = new Set<string>(CONTENT_TAG_CHOICES.map(([key]) => key))

export const CONTENT_TAG_LABELS = Object.fromEntries(CONTENT_TAG_CHOICES) as Record<ContentTagKey, string>

export function contentTagKeysFromMetadata(metadata?: Record<string, unknown>): ContentTagKey[] {
  const manual = metadata?.user_tags
  if (Array.isArray(manual)) {
    const tags = manual.filter(
      (value): value is ContentTagKey => typeof value === 'string' && CONTENT_TAG_KEYS.has(value),
    )
    if (tags.length) return [...new Set(tags)].slice(0, 4)
  }
  const lane = metadata?.lane
  return typeof lane === 'string' && CONTENT_TAG_KEYS.has(lane) ? [lane as ContentTagKey] : []
}

export function normalizeContentTagKeys(values?: string[]): ContentTagKey[] {
  return [...new Set((values || []).filter((value): value is ContentTagKey => CONTENT_TAG_KEYS.has(value)))].slice(0, 4)
}
