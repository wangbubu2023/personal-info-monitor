import { describe, it, expect } from 'vitest'
import {
  failureCodeLabel,
  fulltextStatusLabel,
  rssHealthLabel,
  rssHealthColor,
  formatRate,
  formatLatency,
  formatCooldownRemaining,
  isInCooldown,
  deriveHealthSeverity,
  HEALTH_SEVERITY_ORDER,
} from './fetchHealth'
import type { Source } from '../types'

const baseSource = (overrides: Partial<Source> = {}): Source => ({
  id: 's1',
  name: 'demo',
  type: 'rss',
  url: 'https://example.com/feed',
  fetch_interval: 3600,
  enabled: true,
  use_keyword_filter: false,
  auth_required: false,
  error_count: 0,
  content_count: 0,
  fetch_status: 'ok',
  fetch_strategy: 'rss',
  fetch_status_message: '',
  probe_status: 'not_probed',
  probe_strategy: 'unknown',
  probe_message: '',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...overrides,
})

describe('label maps', () => {
  it('maps known failure codes to Chinese', () => {
    expect(failureCodeLabel('timeout')).toBe('抓取超时')
    expect(failureCodeLabel('ssrf_blocked')).toBe('安全策略拦截')
    expect(failureCodeLabel('http_429')).toBe('请求限流 (429)')
  })

  it('falls back to the raw code for unknown values', () => {
    expect(failureCodeLabel('some_new_code')).toBe('some_new_code')
    expect(failureCodeLabel(null)).toBe('—')
    expect(failureCodeLabel(undefined)).toBe('—')
  })

  it('maps fulltext and rss statuses', () => {
    expect(fulltextStatusLabel('login_required')).toBe('需登录')
    expect(fulltextStatusLabel('full')).toBe('完整正文')
    expect(rssHealthLabel('stale')).toBe('陈旧')
    expect(rssHealthColor('parse_error')).toBe('red')
    expect(rssHealthColor('ok')).toBe('green')
    expect(rssHealthColor(undefined)).toBe('default')
  })
})

describe('formatters', () => {
  it('formats rates as percentages', () => {
    expect(formatRate(0.5)).toBe('50%')
    expect(formatRate(1)).toBe('100%')
    expect(formatRate(null)).toBe('—')
    expect(formatRate(undefined)).toBe('—')
  })

  it('formats latency in ms or s', () => {
    expect(formatLatency(500)).toBe('500 ms')
    expect(formatLatency(1500)).toBe('1.5 s')
    expect(formatLatency(null)).toBe('—')
  })
})

describe('cooldown', () => {
  const now = new Date('2026-06-01T12:00:00Z')

  it('returns remaining minutes when in the future', () => {
    expect(formatCooldownRemaining('2026-06-01T12:30:00Z', now)).toBe('30 分钟')
    expect(isInCooldown('2026-06-01T12:30:00Z', now)).toBe(true)
  })

  it('formats hours and minutes for long cooldowns', () => {
    expect(formatCooldownRemaining('2026-06-01T14:15:00Z', now)).toBe('2 小时 15 分钟')
  })

  it('returns null when elapsed or missing', () => {
    expect(formatCooldownRemaining('2026-06-01T11:00:00Z', now)).toBeNull()
    expect(formatCooldownRemaining(null, now)).toBeNull()
    expect(isInCooldown(undefined, now)).toBe(false)
  })
})

describe('deriveHealthSeverity', () => {
  const now = new Date('2026-06-01T12:00:00Z')

  it('prioritises active cooldown over fetch_status', () => {
    const s = baseSource({ fetch_status: 'ok', cooldown_until: '2026-06-01T12:30:00Z' })
    expect(deriveHealthSeverity(s, now)).toBe('cooling')
  })

  it('maps fetch_status when no cooldown', () => {
    expect(deriveHealthSeverity(baseSource({ fetch_status: 'error' }), now)).toBe('error')
    expect(deriveHealthSeverity(baseSource({ fetch_status: 'warning' }), now)).toBe('warning')
    expect(deriveHealthSeverity(baseSource({ fetch_status: 'ok' }), now)).toBe('ok')
    expect(deriveHealthSeverity(baseSource({ fetch_status: 'unknown' }), now)).toBe('unknown')
  })

  it('orders error before ok for sorting', () => {
    expect(HEALTH_SEVERITY_ORDER.error).toBeLessThan(HEALTH_SEVERITY_ORDER.ok)
    expect(HEALTH_SEVERITY_ORDER.cooling).toBeLessThan(HEALTH_SEVERITY_ORDER.warning)
  })
})
