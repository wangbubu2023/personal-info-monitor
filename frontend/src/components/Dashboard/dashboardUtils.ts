import type { Content, Digest, DigestItem } from '../../types'
import { KEYWORD_MONITORING_ENABLED } from '../../config/features'
import { formatLocalDateTime, parseApiDate } from '../../utils/datetime'

const FULLTEXT_STATUS_LABELS: Record<string, string> = {
  full: '全文',
  partial: '部分',
  summary_only: '摘要',
  title_only: '标题',
  blocked: '受限',
}

export interface DigestItemRecommendationReason {
  why_now?: string
  why_matters?: string
  source_context?: string
  evidence?: string
  caveat?: string
  suggested_action?: string
  confidence?: number
  reason_source?: string
}

function readNumericMetadata(item: DigestItem, key: string): number | undefined {
  const raw = item.metadata?.[key]
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  if (typeof raw === 'string' && raw.trim()) {
    const parsed = Number(raw)
    if (Number.isFinite(parsed)) return parsed
  }
  return undefined
}

function readStringMetadata(item: DigestItem, key: string): string | undefined {
  const raw = item.metadata?.[key]
  if (typeof raw === 'string' && raw.trim()) return raw.trim()
  return undefined
}

export function getDigestItemFinalScore(item: DigestItem): number | undefined {
  const score = readNumericMetadata(item, 'final_score')
  if (score === undefined) return undefined
  return Math.max(0, Math.min(100, score))
}

export function getDigestItemSourceStars(item: DigestItem): number | undefined {
  const stars = readNumericMetadata(item, 'source_stars')
  if (stars === undefined) return undefined
  return Math.max(1, Math.min(3, Math.round(stars)))
}

export function getDigestItemFulltextStatusLabel(item: DigestItem): string | undefined {
  const status = readStringMetadata(item, 'fulltext_status')
  if (!status) return undefined
  return FULLTEXT_STATUS_LABELS[status] || status
}

export function getDigestItemRecommendationReason(item: DigestItem): DigestItemRecommendationReason | undefined {
  const raw = item.metadata?.recommendation_reason
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined
  const record = raw as Record<string, unknown>
  const out: DigestItemRecommendationReason = {}
  for (const key of [
    'why_now',
    'why_matters',
    'source_context',
    'evidence',
    'caveat',
    'suggested_action',
    'reason_source',
  ] as const) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) out[key] = value.trim()
  }
  const confidence = record.confidence
  if (typeof confidence === 'number' && Number.isFinite(confidence)) {
    out.confidence = Math.max(0, Math.min(1, confidence))
  }
  return Object.keys(out).length ? out : undefined
}

export const formatDashboardTime = (dateStr?: string) => {
  if (!dateStr) return ''
  return formatLocalDateTime(dateStr, 'zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    timeZoneName: 'short',
  })
}

export const renderDashboardTimePair = (publish?: string, fetched?: string) => {
  const fetchedText = formatDashboardTime(fetched)
  const publishText = formatDashboardTime(publish)
  return `抓取 ${fetchedText || '--'} / 发布 ${publishText || '--'}`
}

/**
 * 资讯列表排序：优先「抓取/入库时间」再「发布时间」。
 * 若只按发布时间排，「全部」合并多源时老文章（如今日刚抓的 CNN）会沉底，单分类下却很明显。
 */
export function compareDashboardItemsForSort(a: DigestItem, b: DigestItem): number {
  const fb = parseApiDate(b.fetched_at)?.getTime() ?? 0
  const fa = parseApiDate(a.fetched_at)?.getTime() ?? 0
  if (fb !== fa) return fb - fa
  const pb = parseApiDate(b.publish_time)?.getTime() ?? 0
  const pa = parseApiDate(a.publish_time)?.getTime() ?? 0
  return pb - pa
}

export const getDashboardItems = (digest: Digest | undefined, activeTab: string): DigestItem[] => {
  if (!digest) return []

  if (activeTab === 'all') {
    return [
      ...(digest.categories.websites.items || []),
      ...(digest.categories.rss.items || []),
      ...(digest.categories.x_accounts.items || []),
      ...(digest.categories.youtube.items || []),
      ...(digest.categories.podcasts.items || []),
    ].sort(compareDashboardItemsForSort)
  }

  const categoryMap: Record<string, DigestItem[]> = {
    websites: digest.categories.websites.items || [],
    rss: digest.categories.rss.items || [],
    x_accounts: digest.categories.x_accounts.items || [],
    youtube: digest.categories.youtube.items || [],
    podcasts: digest.categories.podcasts.items || [],
  }

  return (categoryMap[activeTab] || []).sort(compareDashboardItemsForSort)
}

export const getDashboardCategoryCount = (digest: Digest | undefined, key: string): number => {
  if (!digest) return 0
  if (key === 'all') {
    return (
      (digest.categories.websites.count || 0) +
      (digest.categories.rss.count || 0) +
      (digest.categories.x_accounts.count || 0) +
      (digest.categories.youtube.count || 0) +
      (digest.categories.podcasts.count || 0)
    )
  }

  const countMap: Record<string, number> = {
    websites: digest.categories.websites.count || 0,
    rss: digest.categories.rss.count || 0,
    x_accounts: digest.categories.x_accounts.count || 0,
    youtube: digest.categories.youtube.count || 0,
  }
  return countMap[key] || 0
}

const DIGEST_PREVIEW_MIN_LEN = 12
const DIGEST_PREVIEW_MAX_LEN = 280

/** 摘要字段去 HTML，避免列表上出现「有数据但看不见」 */
export function digestSummaryPlain(raw?: string | null): string {
  const s = (raw || '').trim()
  if (!s) return ''
  return s.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
}

/** 与后端 `digest._digest_snippet_from_text` 对齐的纯文本截取 */
export function makeDigestBodyPreview(fullContent?: string | null): string | undefined {
  const raw = (fullContent || '').trim()
  if (!raw) return undefined
  const plain = raw
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (plain.length < DIGEST_PREVIEW_MIN_LEN) return undefined
  if (plain.length <= DIGEST_PREVIEW_MAX_LEN) return plain
  let cut = plain.slice(0, DIGEST_PREVIEW_MAX_LEN)
  const lastSpace = cut.lastIndexOf(' ')
  if (lastSpace > DIGEST_PREVIEW_MAX_LEN / 2) cut = cut.slice(0, lastSpace)
  return `${cut.trim()}…`
}

/** 与后端 `_digest_list_preview` 一致：正文 → 译摘要 → 摘要（供搜索列表等） */
export function makeDigestListPreview(
  fullContent?: string | null,
  translatedSummary?: string | null,
  summary?: string | null,
): string | undefined {
  return (
    makeDigestBodyPreview(fullContent) ??
    makeDigestBodyPreview(translatedSummary) ??
    makeDigestBodyPreview(summary)
  )
}

/**
 * 资讯卡片上展示的摘要/摘录：与 digest 摘录上限一致，避免 summary 误存全文时撑爆 DOM；
 * 短于 `DIGEST_PREVIEW_MIN_LEN` 的纯文本仍原样展示。
 */
export function capDashboardListPreview(raw: string): string {
  const capped = makeDigestBodyPreview(raw)
  if (capped !== undefined) return capped
  return raw.replace(/\s+/g, ' ').trim()
}

export const contentToDigestItem = (content: Content): DigestItem => {
  const body_preview = makeDigestListPreview(
    content.full_content,
    content.translated_summary,
    content.summary,
  )
  return {
    id: content.id,
    source_name: content.source_name || '',
    title: content.title,
    translated_title: content.translated_title,
    summary: content.summary,
    translated_summary: content.translated_summary,
    ...(body_preview !== undefined ? { body_preview } : {}),
    url: content.original_url,
    publish_time: content.publish_time,
    fetched_at: content.fetched_at,
    read_status: content.read_status,
    favorited: content.favorited,
    keyword_matches: KEYWORD_MONITORING_ENABLED ? (content.keyword_matches || []) : [],
    metadata: content.metadata || {},
  }
}

/** 阅读页链接：可附带 translate，以及返回时恢复的 `?tab=` 或 `?search=` */
export function buildReaderPath(
  id: string,
  opts?: { translate?: boolean; tab?: string; search?: string },
): string {
  const p = new URLSearchParams()
  if (opts?.translate) p.set('translate', '1')
  if (opts?.search) p.set('search', opts.search)
  else if (opts?.tab && opts.tab !== 'all') p.set('tab', opts.tab)
  const q = p.toString()
  return q ? `/reader/${id}?${q}` : `/reader/${id}`
}

/** 资讯中心首页：`search` 优先（与当前页是否为搜索视图一致），否则保留分类 tab */
export function buildDashboardHomePath(tab?: string | null, search?: string | null): string {
  if (search) return `/?search=${encodeURIComponent(search)}`
  if (tab && tab !== 'all') return `/?tab=${encodeURIComponent(tab)}`
  return '/'
}
