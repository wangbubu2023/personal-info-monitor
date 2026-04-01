import { describe, expect, it } from 'vitest'

import { normalizeApiBaseURL } from './api'

describe('normalizeApiBaseURL', () => {
  it('adds the api suffix when a raw backend origin is provided', () => {
    expect(normalizeApiBaseURL('http://127.0.0.1:8000')).toBe('http://127.0.0.1:8000/api')
  })

  it('preserves a base url that already targets /api', () => {
    expect(normalizeApiBaseURL('http://127.0.0.1:8000/api')).toBe('http://127.0.0.1:8000/api')
    expect(normalizeApiBaseURL('/api')).toBe('/api')
  })

  it('falls back to the proxied api path when no value is provided', () => {
    expect(normalizeApiBaseURL('')).toBe('/api')
  })
})
