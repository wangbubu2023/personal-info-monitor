import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Source } from '../../types'
import {
  SOURCE_BACKUP_VERSION,
  SOURCE_CSV_COLUMNS,
  buildBackupFilename,
  buildSourceBackup,
  buildSourceCsv,
  downloadSourceBackup,
} from './exportUtils'

function makeSource(partial: Partial<Source> = {}): Source {
  return {
    id: 'id-1',
    name: 'Example',
    type: 'website',
    url: 'https://example.com',
    fetch_interval: 60,
    enabled: true,
    use_keyword_filter: false,
    auth_required: false,
    error_count: 0,
    content_count: 0,
    fetch_status: 'ok',
    fetch_strategy: 'scrape',
    fetch_status_message: '',
    probe_status: 'ok',
    probe_strategy: 'scrape',
    probe_message: '',
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    ...partial,
  }
}

describe('exportUtils', () => {
  it('wraps sources into the backup payload', () => {
    const sources = [makeSource(), makeSource({ id: 'id-2', name: 'Two' })]
    const payload = buildSourceBackup(sources, '2026-04-22T08:30:00Z')
    expect(payload).toEqual({
      version: SOURCE_BACKUP_VERSION,
      kind: 'pim.sources',
      exported_at: '2026-04-22T08:30:00Z',
      source_count: 2,
      sources,
    })
  })

  it('formats backup filename with minute-precision timestamp', () => {
    const filename = buildBackupFilename({ date: new Date(2026, 3, 22, 8, 5) })
    expect(filename).toBe('pim-sources-backup-20260422-0805.json')
  })

  it('marks selected filenames distinctly', () => {
    const filename = buildBackupFilename({ selected: true, date: new Date(2026, 3, 22, 8, 5) })
    expect(filename).toBe('pim-sources-backup-20260422-0805-selected.json')
  })

  it('uses .csv extension when format=csv', () => {
    const filename = buildBackupFilename({ date: new Date(2026, 3, 22, 8, 5), format: 'csv' })
    expect(filename).toBe('pim-sources-backup-20260422-0805.csv')
  })

  describe('buildSourceCsv', () => {
    it('emits BOM + header row + CSV rows with CRLF and compatible leading columns', () => {
      const sources = [
        makeSource({
          name: 'Example',
          url: 'https://example.com',
          extra_urls: ['https://example.com/rss'],
          metadata: { description: 'Daily feed' },
        }),
      ]
      const csv = buildSourceCsv(sources)
      expect(csv.startsWith('\ufeff')).toBe(true)
      const [header, dataRow] = csv.replace(/^\ufeff/, '').trim().split('\r\n')
      expect(header).toBe(SOURCE_CSV_COLUMNS.join(','))
      // First three columns must remain name,description,url for round-trip import.
      expect(dataRow.startsWith('Example,Daily feed,https://example.com,')).toBe(true)
      expect(dataRow).toContain('https://example.com/rss')
    })

    it('escapes commas, quotes, and newlines', () => {
      const sources = [
        makeSource({
          name: 'A, B',
          url: 'https://example.com',
          metadata: { description: 'She said "hi"\nnewline' },
        }),
      ]
      const csv = buildSourceCsv(sources)
      expect(csv).toContain('"A, B"')
      expect(csv).toContain('"She said ""hi""\nnewline"')
    })
  })

  describe('downloadSourceBackup', () => {
    const originalCreate = URL.createObjectURL
    const originalRevoke = URL.revokeObjectURL

    beforeEach(() => {
      vi.useFakeTimers()
      URL.createObjectURL = vi.fn(() => 'blob:mock')
      URL.revokeObjectURL = vi.fn()
    })

    afterEach(() => {
      vi.useRealTimers()
      URL.createObjectURL = originalCreate
      URL.revokeObjectURL = originalRevoke
    })

    it('creates a JSON blob anchor and returns the filename', () => {
      const clickSpy = vi.fn()
      const appendSpy = vi.spyOn(document.body, 'appendChild')
      vi.spyOn(document, 'createElement').mockImplementationOnce(() => {
        const anchor = document.createElementNS('http://www.w3.org/1999/xhtml', 'a') as HTMLAnchorElement
        anchor.click = clickSpy
        return anchor
      })

      const filename = downloadSourceBackup([makeSource()], { filename: 'custom.json' })

      expect(filename).toBe('custom.json')
      expect(URL.createObjectURL).toHaveBeenCalledTimes(1)
      expect(clickSpy).toHaveBeenCalledTimes(1)
      expect(appendSpy).toHaveBeenCalled()
      vi.runAllTimers()
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock')
    })
  })
})
