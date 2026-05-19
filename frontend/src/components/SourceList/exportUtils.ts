import type { Source } from '../../types'

export type SourceBackupFormat = 'json' | 'csv'

/** 备份文件顶层结构。`version` 便于未来兼容性升级，`kind` 用于区分 PIM 其他导出物。 */
export interface SourceBackupPayload {
  version: number
  kind: 'pim.sources'
  exported_at: string
  source_count: number
  sources: Source[]
}

export const SOURCE_BACKUP_VERSION = 1

export function buildSourceBackup(
  sources: Source[],
  exportedAt: string = new Date().toISOString(),
): SourceBackupPayload {
  return {
    version: SOURCE_BACKUP_VERSION,
    kind: 'pim.sources',
    exported_at: exportedAt,
    source_count: sources.length,
    sources,
  }
}

/** 生成 `pim-sources-backup-YYYYMMDD-HHmm[-selected].{json|csv}` 文件名。 */
export function buildBackupFilename(
  options: { selected?: boolean; date?: Date; format?: SourceBackupFormat } = {},
): string {
  const d = options.date ?? new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  const stamp = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`
  const suffix = options.selected ? '-selected' : ''
  const ext = options.format === 'csv' ? 'csv' : 'json'
  return `pim-sources-backup-${stamp}${suffix}.${ext}`
}

/** 首行与现有 CSV 导入兼容（name/description/url 位于前三列），后续列为辅助信息。 */
export const SOURCE_CSV_COLUMNS = [
  'name',
  'description',
  'url',
  'type',
  'extra_urls',
  'enabled',
  'fetch_interval',
  'auth_required',
  'auth_config_id',
  'last_fetched_at',
  'fetch_status',
  'fetch_strategy',
] as const

function csvEscape(value: unknown): string {
  if (value === null || value === undefined) return ''
  const s = typeof value === 'string' ? value : String(value)
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`
  return s
}

function extractDescription(source: Source): string {
  const meta = source.metadata
  if (meta && typeof meta === 'object') {
    const desc = (meta as Record<string, unknown>).description
    if (typeof desc === 'string') return desc
  }
  return ''
}

export function buildSourceCsv(sources: Source[]): string {
  const rows: string[] = [SOURCE_CSV_COLUMNS.join(',')]
  for (const s of sources) {
    const extraUrls = Array.isArray(s.extra_urls) ? s.extra_urls.join(';') : ''
    const row = [
      s.name,
      extractDescription(s),
      s.url,
      s.type,
      extraUrls,
      s.enabled ? 'true' : 'false',
      s.fetch_interval,
      s.auth_required ? 'true' : 'false',
      s.auth_config_id ?? '',
      s.last_fetched_at ?? '',
      s.fetch_status,
      s.fetch_strategy,
    ].map(csvEscape)
    rows.push(row.join(','))
  }
  // Excel 识别中文 UTF-8 需要 BOM；`\r\n` 行尾兼容性最好。
  return `\ufeff${rows.join('\r\n')}\r\n`
}

interface DownloadOptions {
  selected?: boolean
  filename?: string
  format?: SourceBackupFormat
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  try {
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.rel = 'noopener'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }
}

/**
 * 触发浏览器下载备份文件。默认 JSON（完整字段，可无损恢复）；`format: 'csv'` 生成 Excel 友好版本（有损）。
 */
export function downloadSourceBackup(sources: Source[], options: DownloadOptions = {}): string {
  const format: SourceBackupFormat = options.format ?? 'json'
  const filename =
    options.filename ?? buildBackupFilename({ selected: options.selected, format })

  if (format === 'csv') {
    const blob = new Blob([buildSourceCsv(sources)], { type: 'text/csv;charset=utf-8' })
    triggerDownload(blob, filename)
    return filename
  }

  const payload = buildSourceBackup(sources)
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: 'application/json;charset=utf-8',
  })
  triggerDownload(blob, filename)
  return filename
}
