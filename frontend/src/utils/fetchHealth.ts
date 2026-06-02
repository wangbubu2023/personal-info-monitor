/**
 * Presentation helpers for the fetch-health views (enhancement plan).
 *
 * Pure functions only — Chinese label maps for failure / fulltext / RSS-health
 * codes, plus cooldown / latency / rate formatting. Kept free of React so they
 * can be unit-tested directly and reused across the per-source drawer and the
 * global "抓取健康" quality centre.
 */

import type { FetchProfileSummary, RssHealthMeta, Source } from '../types'

/** Chinese labels for FetchFailureCode (backend: domains.fetch.failures). */
export const FAILURE_CODE_LABELS: Record<string, string> = {
  timeout: '抓取超时',
  dns_error: '域名解析失败',
  tls_error: 'TLS/SSL 错误',
  connection_error: '网络连接失败',
  http_403: '访问被拒绝 (403)',
  http_429: '请求限流 (429)',
  http_5xx: '服务器错误 (5xx)',
  http_client_error: '请求错误 (4xx)',
  redirect_blocked: '重定向被拦截',
  ssrf_blocked: '安全策略拦截',
  login_required: '需要登录',
  session_expired: '登录态失效',
  bot_wall: '反爬墙',
  captcha: '验证码/人机校验',
  rss_stale: 'RSS 无更新',
  rss_parse_error: 'RSS 解析失败',
  html_parse_empty: '解析无内容',
  body_incomplete: '正文不完整',
  unknown: '未知失败',
  // Legacy / pipeline codes that may still appear in last_fetch_outcome.
  fetch_failed: '抓取失败',
  no_new_content: '暂无新内容',
}

/** Chinese labels for the rich fulltext quality statuses. */
export const FULLTEXT_STATUS_LABELS: Record<string, string> = {
  full: '完整正文',
  partial: '部分正文',
  summary_only: '仅摘要',
  title_only: '仅标题',
  login_required: '需登录',
  bot_wall: '反爬墙',
  captcha: '验证码',
  boilerplate_only: '模板页',
  non_article: '非文章页',
  empty: '空内容',
  blocked: '受阻',
}

export const RSS_HEALTH_LABELS: Record<string, string> = {
  ok: '健康',
  stale: '陈旧',
  empty: '空 feed',
  parse_error: '解析失败',
}

const RSS_HEALTH_COLORS: Record<string, string> = {
  ok: 'green',
  stale: 'gold',
  empty: 'default',
  parse_error: 'red',
}

export function failureCodeLabel(code?: string | null): string {
  if (!code) return '—'
  return FAILURE_CODE_LABELS[code] || code
}

export function fulltextStatusLabel(status?: string | null): string {
  if (!status) return '—'
  return FULLTEXT_STATUS_LABELS[status] || status
}

export function rssHealthLabel(status?: string | null): string {
  if (!status) return '—'
  return RSS_HEALTH_LABELS[status] || status
}

export function rssHealthColor(status?: string | null): string {
  if (!status) return 'default'
  return RSS_HEALTH_COLORS[status] || 'default'
}

/** Format a 0..1 rate as a percentage string, or '—' when unknown. */
export function formatRate(rate?: number | null): string {
  if (rate === null || rate === undefined || Number.isNaN(rate)) return '—'
  return `${Math.round(rate * 100)}%`
}

/** Human-readable latency from milliseconds. */
export function formatLatency(ms?: number | null): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

/**
 * Format the remaining cooldown relative to ``now``. Returns null when there is
 * no active cooldown (missing / already elapsed).
 */
export function formatCooldownRemaining(
  cooldownUntil?: string | null,
  now: Date = new Date(),
): string | null {
  if (!cooldownUntil) return null
  const deadline = new Date(cooldownUntil.replace(' ', 'T'))
  if (Number.isNaN(deadline.getTime())) return null
  const diffMs = deadline.getTime() - now.getTime()
  if (diffMs <= 0) return null
  const mins = Math.ceil(diffMs / 60000)
  if (mins < 60) return `${mins} 分钟`
  const hours = Math.floor(mins / 60)
  const rem = mins % 60
  return rem > 0 ? `${hours} 小时 ${rem} 分钟` : `${hours} 小时`
}

export function isInCooldown(cooldownUntil?: string | null, now: Date = new Date()): boolean {
  return formatCooldownRemaining(cooldownUntil, now) !== null
}

export type HealthSeverity = 'error' | 'warning' | 'cooling' | 'ok' | 'unknown'

/**
 * Derive a single health severity for sorting / summarising a source, combining
 * the live fetch_status with the cooldown state.
 */
export function deriveHealthSeverity(source: Source, now: Date = new Date()): HealthSeverity {
  if (isInCooldown(source.cooldown_until, now)) return 'cooling'
  switch (source.fetch_status) {
    case 'error':
      return 'error'
    case 'warning':
      return 'warning'
    case 'ok':
      return 'ok'
    default:
      return 'unknown'
  }
}

export const HEALTH_SEVERITY_ORDER: Record<HealthSeverity, number> = {
  error: 0,
  cooling: 1,
  warning: 2,
  unknown: 3,
  ok: 4,
}

export const HEALTH_SEVERITY_META: Record<HealthSeverity, { label: string; color: string }> = {
  error: { label: '失败', color: '#ff4d4f' },
  cooling: { label: '冷却中', color: '#722ed1' },
  warning: { label: '告警', color: '#faad14' },
  ok: { label: '正常', color: '#52c41a' },
  unknown: { label: '未抓取', color: '#8a96a5' },
}

/** Whether the source carries any 7d profile activity worth showing. */
export function hasProfileActivity(summary?: FetchProfileSummary | null): boolean {
  return !!summary && summary.attempts_7d > 0
}

export function rssHealthIsActionable(health?: RssHealthMeta | null): boolean {
  if (!health || !health.status) return false
  return health.status === 'parse_error' || health.status === 'empty'
}
