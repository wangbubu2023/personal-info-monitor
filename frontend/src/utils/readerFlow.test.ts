import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  compareReaderMetrics,
  getReaderNeighbor,
  recordReaderInteraction,
  saveReaderMetricsBaseline,
  saveReaderSequence,
} from './readerFlow'
import type { DigestItem } from '../types'

const makeItem = (id: string): DigestItem => ({
  id,
  title: `Item ${id}`,
  summary: '',
  source_id: 'source-1',
  source_name: 'Source',
  url: `https://example.com/${id}`,
  publish_time: '2026-07-07T00:00:00',
  read_status: false,
  favorited: false,
  keyword_matches: [],
})

describe('readerFlow', () => {
  beforeEach(() => {
    const store = new Map<string, string>()
    Object.defineProperty(window, 'localStorage', {
      value: {
        getItem: vi.fn((key: string) => store.get(key) || null),
        setItem: vi.fn((key: string, value: string) => store.set(key, value)),
        clear: vi.fn(() => store.clear()),
      },
      configurable: true,
    })
  })

  beforeEach(() => {
    window.localStorage.clear()
  })

  it('stores reader sequence and finds neighbors', () => {
    saveReaderSequence([makeItem('a'), makeItem('b'), makeItem('c')])

    expect(getReaderNeighbor('b', -1)?.id).toBe('a')
    expect(getReaderNeighbor('b', 1)?.id).toBe('c')
    expect(getReaderNeighbor('c', 1)).toBeNull()
  })

  it('compares keyboard and click interactions against a baseline', () => {
    recordReaderInteraction('click', 'open')
    saveReaderMetricsBaseline()

    recordReaderInteraction('keyboard', 'navigate')
    recordReaderInteraction('click', 'read_later')
    recordReaderInteraction('keyboard', 'hide')

    const comparison = compareReaderMetrics()
    expect(comparison.delta.keyboard).toBe(2)
    expect(comparison.delta.clicks).toBe(1)
    expect(comparison.delta.readLater).toBe(1)
    expect(comparison.delta.hidden).toBe(1)
    expect(comparison.keyboardShare).toBeCloseTo(2 / 3)
  })

  it('tolerates metrics persisted before the hidden field existed', () => {
    window.localStorage.setItem(
      'pim.reader.interactionMetrics.v1',
      JSON.stringify({ keyboard: 2, clicks: 1, opened: 1, readLater: 0 }),
    )

    const next = recordReaderInteraction('keyboard', 'hide')
    expect(next.hidden).toBe(1)
    expect(next.keyboard).toBe(3)
  })
})
