/**
 * Canonical list of monitoring source types for the frontend.
 *
 * This is the **single source of truth** the UI should read from. Historically
 * the same labels were duplicated across source list filters, the editor
 * modal, the dashboard tabs, and the task-prompt settings — the 2026-04-20
 * audit (Q3) called this out as drift-prone. New types are added here first,
 * then kept in sync with `backend/app/data/source_types.py` (which also
 * exposes them via `GET /api/system/source-types`).
 */

export type SourceTypeKey = 'rss' | 'website' | 'x' | 'youtube' | 'podcast'

export interface SourceTypeInfo {
  key: SourceTypeKey
  /** Full Chinese label used in forms and prompt pickers. */
  label: string
  /** Compact label used in pill tabs and tight tables. */
  shortLabel: string
  description: string
  /** Tailwind-ish accent token consumed by the dashboard. */
  accent: string
  /** Feature-flag gate — false entries should never appear in pickers. */
  enabled: boolean
}

export const SOURCE_TYPE_CATALOG: readonly SourceTypeInfo[] = Object.freeze([
  {
    key: 'rss',
    label: 'RSS',
    shortLabel: 'RSS',
    description: '标准 RSS / Atom 订阅源，按 Feed 条目抓取。',
    accent: 'blue',
    enabled: true,
  },
  {
    key: 'website',
    label: '网站 / 博客',
    shortLabel: '网站',
    description: '普通网页与博客，支持 HTTP 及 Playwright 回退。',
    accent: 'slate',
    enabled: true,
  },
  {
    key: 'x',
    label: 'X (Twitter)',
    shortLabel: 'X',
    description: 'X 时间线；可经 RSSHub / Nitter / API 抓取。',
    accent: 'cyan',
    enabled: true,
  },
  {
    key: 'youtube',
    label: 'YouTube',
    shortLabel: 'YouTube',
    description: 'YouTube 频道视频与描述。',
    accent: 'red',
    enabled: true,
  },
  {
    key: 'podcast',
    label: '播客',
    shortLabel: '播客',
    description: '播客 RSS。',
    accent: 'violet',
    enabled: false,
  },
])

export const ENABLED_SOURCE_TYPES = SOURCE_TYPE_CATALOG.filter((info) => info.enabled)

/** Map `SourceType -> Chinese label`, falling back to the key itself. */
export function sourceTypeLabel(key: string | null | undefined, fallback?: string): string {
  if (!key) return fallback ?? ''
  const hit = SOURCE_TYPE_CATALOG.find((info) => info.key === (key as SourceTypeKey))
  return hit ? hit.label : fallback ?? key
}

export function sourceTypeShortLabel(key: string | null | undefined, fallback?: string): string {
  if (!key) return fallback ?? ''
  const hit = SOURCE_TYPE_CATALOG.find((info) => info.key === (key as SourceTypeKey))
  return hit ? hit.shortLabel : fallback ?? key
}

export interface SourceTypeFilterOption {
  key: string
  label: string
}

/** Build the "全部" + enabled types option list used by filter pills. */
export function sourceTypeFilterOptions(allLabel = '全部'): SourceTypeFilterOption[] {
  return [
    { key: 'all', label: allLabel },
    ...ENABLED_SOURCE_TYPES.map((info) => ({ key: info.key, label: info.label })),
  ]
}
