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

export type DashboardSortMode = 'time_desc' | 'score_desc'

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
  const score = readNumericMetadata(item, 'final_score') ?? readNumericMetadata(item, 'article_score')
  if (score === undefined) return undefined
  return Math.max(0, Math.min(100, score))
}

export function getDigestItemScoreDeferred(item: DigestItem): boolean {
  if (getDigestItemFinalScore(item) !== undefined) return false
  const status = readStringMetadata(item, 'selection_status')
  if (status === 'deferred') return true
  return readStringMetadata(item, 'fetch_acceptance') === 'incomplete'
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

const FUTURE_PUBLISH_TOLERANCE_MS = 15 * 60 * 1000

function getDashboardSortTimestamp(item: DigestItem): number {
  const publishMs = parseApiDate(item.publish_time)?.getTime()
  const fetchedMs = parseApiDate(item.fetched_at)?.getTime()
  if (publishMs === undefined && fetchedMs === undefined) return 0
  if (publishMs === undefined) return fetchedMs ?? 0
  if (fetchedMs === undefined) return publishMs
  return publishMs > fetchedMs + FUTURE_PUBLISH_TOLERANCE_MS ? fetchedMs : publishMs
}

function compareDashboardItemsByTimeDesc(a: DigestItem, b: DigestItem): number {
  const pb = getDashboardSortTimestamp(b)
  const pa = getDashboardSortTimestamp(a)
  if (pb !== pa) return pb - pa
  const fb = parseApiDate(b.fetched_at)?.getTime() ?? 0
  const fa = parseApiDate(a.fetched_at)?.getTime() ?? 0
  return fb - fa
}

/** 资讯列表排序：默认按时间倒排；也支持按评分倒排，缺失评分的条目排在最后。 */
export function compareDashboardItemsForSort(
  a: DigestItem,
  b: DigestItem,
  sortMode: DashboardSortMode = 'time_desc',
): number {
  if (sortMode === 'score_desc') {
    const bs = getDigestItemFinalScore(b) ?? -1
    const as = getDigestItemFinalScore(a) ?? -1
    if (bs !== as) return bs - as
  }
  return compareDashboardItemsByTimeDesc(a, b)
}

export const getDashboardItems = (
  digest: Digest | undefined,
  activeTab: string,
  sortMode: DashboardSortMode = 'time_desc',
): DigestItem[] => {
  if (!digest) return []

  if (activeTab === 'all') {
    return [
      ...(digest.categories.websites.items || []),
      ...(digest.categories.rss.items || []),
      ...(digest.categories.x_accounts.items || []),
      ...(digest.categories.youtube.items || []),
      ...(digest.categories.podcasts.items || []),
    ].sort((a, b) => compareDashboardItemsForSort(a, b, sortMode))
  }

  const categoryMap: Record<string, DigestItem[]> = {
    websites: digest.categories.websites.items || [],
    rss: digest.categories.rss.items || [],
    x_accounts: digest.categories.x_accounts.items || [],
    youtube: digest.categories.youtube.items || [],
    podcasts: digest.categories.podcasts.items || [],
  }

  return (categoryMap[activeTab] || []).sort((a, b) => compareDashboardItemsForSort(a, b, sortMode))
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

/** 与后端 `_digest_list_preview` 一致：译摘要 → 摘要 → 正文摘录 */
export function makeDigestListPreview(
  fullContent?: string | null,
  translatedSummary?: string | null,
  summary?: string | null,
): string | undefined {
  return (
    makeDigestBodyPreview(translatedSummary) ??
    makeDigestBodyPreview(summary) ??
    makeDigestBodyPreview(fullContent)
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
    source_id: content.source_id,
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

export function buildDashboardSourcePath(sourceId?: string | null, sourceName?: string | null): string {
  if (!sourceId) return '/timeline'
  const p = new URLSearchParams()
  p.set('source_id', sourceId)
  if (sourceName) p.set('source', sourceName)
  return `/timeline?${p.toString()}`
}

/** 阅读页链接：可附带 translate，以及返回时恢复的 `?tab=`、`?search=`、`?source_id=` 或 `?from=` */
export function buildReaderPath(
  id: string,
  opts?: {
    translate?: boolean
    tab?: string
    search?: string
    sourceId?: string
    sourceName?: string
    from?: string
  },
): string {
  const p = new URLSearchParams()
  if (opts?.translate) p.set('translate', '1')
  if (opts?.from) p.set('from', opts.from)
  if (opts?.search) p.set('search', opts.search)
  if (opts?.sourceId) {
    p.set('source_id', opts.sourceId)
    if (opts.sourceName) p.set('source', opts.sourceName)
  }
  else if (opts?.tab && opts.tab !== 'all') p.set('tab', opts.tab)
  const q = p.toString()
  return q ? `/reader/${id}?${q}` : `/reader/${id}`
}

/** 全部动态页：保留搜索/信源过滤上下文，否则保留分类 tab */
export function buildDashboardHomePath(
  tab?: string | null,
  search?: string | null,
  sourceId?: string | null,
  sourceName?: string | null,
): string {
  const p = new URLSearchParams()
  if (search) p.set('search', search)
  if (sourceId) {
    p.set('source_id', sourceId)
    if (sourceName) p.set('source', sourceName)
  }
  const q = p.toString()
  if (q) return `/timeline?${q}`
  if (tab && tab !== 'all') return `/timeline?tab=${encodeURIComponent(tab)}`
  return '/timeline'
}
