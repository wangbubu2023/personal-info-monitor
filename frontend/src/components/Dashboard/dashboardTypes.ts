import { ENABLED_SOURCE_TYPES, sourceTypeLabel } from '../../config/sourceTypes'
import type { SourceType } from '../../types'

export interface CategoryTab {
  key: string
  label: string
  type: SourceType | 'all'
}

// Dashboard uses stable `key`s (e.g. "websites", "x_accounts") that pre-date
// the catalog; keep a compatibility map so deep links and e2e fixtures that
// use those keys continue to work while the labels themselves stay synced
// with the catalog.
const DASHBOARD_KEY_BY_TYPE: Partial<Record<SourceType, string>> = {
  website: 'websites',
  rss: 'rss',
  x: 'x_accounts',
  youtube: 'youtube',
  podcast: 'podcasts',
}

export const DASHBOARD_CATEGORIES: CategoryTab[] = [
  { key: 'all', label: '全部', type: 'all' },
  ...ENABLED_SOURCE_TYPES.map<CategoryTab>((info) => ({
    key: DASHBOARD_KEY_BY_TYPE[info.key as SourceType] ?? info.key,
    label: sourceTypeLabel(info.key),
    type: info.key as SourceType,
  })),
]
