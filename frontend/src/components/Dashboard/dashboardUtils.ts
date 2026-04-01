import type { Content, Digest, DigestItem } from '../../types'
import { KEYWORD_MONITORING_ENABLED } from '../../config/features'
import { formatLocalDateTime, parseApiDate } from '../../utils/datetime'

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

export const getDashboardItems = (digest: Digest | undefined, activeTab: string): DigestItem[] => {
  if (!digest) return []

  if (activeTab === 'all') {
    return [
      ...(digest.categories.websites.items || []),
      ...(digest.categories.x_accounts.items || []),
      ...(digest.categories.youtube.items || []),
    ].sort((a, b) =>
      (parseApiDate(b.publish_time || b.fetched_at)?.getTime() || 0) - (parseApiDate(a.publish_time || a.fetched_at)?.getTime() || 0)
    )
  }

  const categoryMap: Record<string, DigestItem[]> = {
    websites: digest.categories.websites.items || [],
    x_accounts: digest.categories.x_accounts.items || [],
    youtube: digest.categories.youtube.items || [],
  }

  return (categoryMap[activeTab] || []).sort((a, b) =>
    (parseApiDate(b.publish_time || b.fetched_at)?.getTime() || 0) - (parseApiDate(a.publish_time || a.fetched_at)?.getTime() || 0)
  )
}

export const getDashboardCategoryCount = (digest: Digest | undefined, key: string): number => {
  if (!digest) return 0
  if (key === 'all') {
    return (
      (digest.categories.websites.count || 0) +
      (digest.categories.x_accounts.count || 0) +
      (digest.categories.youtube.count || 0)
    )
  }

  const countMap: Record<string, number> = {
    websites: digest.categories.websites.count || 0,
    x_accounts: digest.categories.x_accounts.count || 0,
    youtube: digest.categories.youtube.count || 0,
  }
  return countMap[key] || 0
}

export const contentToDigestItem = (content: Content): DigestItem => ({
  id: content.id,
  source_name: content.source_name || '',
  title: content.title,
  translated_title: content.translated_title,
  summary: content.summary,
  translated_summary: content.translated_summary,
  url: content.original_url,
  publish_time: content.publish_time,
  fetched_at: content.fetched_at,
  read_status: content.read_status,
  favorited: content.favorited,
  keyword_matches: KEYWORD_MONITORING_ENABLED ? (content.keyword_matches || []) : [],
  metadata: content.metadata || {},
})
