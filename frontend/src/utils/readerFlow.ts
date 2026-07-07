import type { DigestItem } from '../types'

const SEQUENCE_KEY = 'pim.reader.sequence.v1'
const METRICS_KEY = 'pim.reader.interactionMetrics.v1'

export interface ReaderSequenceEntry {
  id: string
  title: string
}

export interface ReaderSequence {
  entries: ReaderSequenceEntry[]
  updatedAt: string
}

export interface ReaderInteractionMetrics {
  keyboard: number
  clicks: number
  opened: number
  markedRead: number
  readLater: number
  lastEventAt?: string
}

export interface ReaderInteractionComparison {
  baseline: ReaderInteractionMetrics
  current: ReaderInteractionMetrics
  delta: ReaderInteractionMetrics
  keyboardShare: number
}

const EMPTY_METRICS: ReaderInteractionMetrics = {
  keyboard: 0,
  clicks: 0,
  opened: 0,
  markedRead: 0,
  readLater: 0,
}

function emptyMetrics(): ReaderInteractionMetrics {
  return { ...EMPTY_METRICS }
}

function readJson<T>(key: string, fallback: T): T {
  if (typeof window === 'undefined') return fallback
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

function writeJson(key: string, value: unknown): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // localStorage may be unavailable in private contexts; metrics are best-effort.
  }
}

export function saveReaderSequence(items: DigestItem[]): void {
  const entries = items
    .filter((item) => item.id)
    .map((item) => ({
      id: item.id,
      title: item.translated_title || item.title || item.id,
    }))
  writeJson(SEQUENCE_KEY, { entries, updatedAt: new Date().toISOString() })
}

export function getReaderNeighbor(id: string | undefined, direction: -1 | 1): ReaderSequenceEntry | null {
  if (!id) return null
  const sequence = readJson<ReaderSequence>(SEQUENCE_KEY, { entries: [], updatedAt: '' })
  const index = sequence.entries.findIndex((entry) => entry.id === id)
  if (index < 0) return null
  return sequence.entries[index + direction] || null
}

export function readReaderMetrics(): ReaderInteractionMetrics {
  return readJson<ReaderInteractionMetrics>(METRICS_KEY, emptyMetrics())
}

export function saveReaderMetricsBaseline(metrics: ReaderInteractionMetrics = readReaderMetrics()): void {
  writeJson(`${METRICS_KEY}.baseline`, metrics)
}

export function compareReaderMetrics(): ReaderInteractionComparison {
  const baseline = readJson<ReaderInteractionMetrics>(`${METRICS_KEY}.baseline`, emptyMetrics())
  const current = readReaderMetrics()
  const delta: ReaderInteractionMetrics = {
    keyboard: current.keyboard - baseline.keyboard,
    clicks: current.clicks - baseline.clicks,
    opened: current.opened - baseline.opened,
    markedRead: current.markedRead - baseline.markedRead,
    readLater: current.readLater - baseline.readLater,
    lastEventAt: current.lastEventAt,
  }
  const totalInteractions = Math.max(1, delta.keyboard + delta.clicks)
  return {
    baseline,
    current,
    delta,
    keyboardShare: delta.keyboard / totalInteractions,
  }
}

export function recordReaderInteraction(
  channel: 'keyboard' | 'click',
  action: 'open' | 'mark_read' | 'read_later' | 'navigate',
): ReaderInteractionMetrics {
  const next = { ...readReaderMetrics(), lastEventAt: new Date().toISOString() }
  if (channel === 'keyboard') next.keyboard += 1
  else next.clicks += 1
  if (action === 'open') next.opened += 1
  if (action === 'mark_read') next.markedRead += 1
  if (action === 'read_later') next.readLater += 1
  writeJson(METRICS_KEY, next)
  return next
}
