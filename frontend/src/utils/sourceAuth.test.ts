import { describe, expect, it } from 'vitest'
import {
  normalizeHost,
  resolveSiteUrlForAuth,
  isXCookieProfile,
  getAuthConfigDisplayName,
  getDefaultSharedXAuthConfigId,
} from './sourceAuth'
import type { AuthConfig } from '../services/configs'

// --- normalizeHost ---
describe('normalizeHost', () => {
  it('returns empty string for undefined', () => {
    expect(normalizeHost(undefined)).toBe('')
  })

  it('strips www prefix', () => {
    expect(normalizeHost('https://www.example.com')).toBe('example.com')
  })

  it('lowercases the hostname', () => {
    expect(normalizeHost('https://EXAMPLE.COM')).toBe('example.com')
  })

  it('prepends https:// when scheme is absent', () => {
    expect(normalizeHost('example.com')).toBe('example.com')
  })

  it('returns empty string for invalid URL', () => {
    expect(normalizeHost('not a url !!!')).toBe('')
  })
})

// --- resolveSiteUrlForAuth ---
describe('resolveSiteUrlForAuth', () => {
  it('converts host to https origin', () => {
    expect(resolveSiteUrlForAuth('www.example.com')).toBe('https://example.com')
  })

  it('returns value as-is when host cannot be resolved', () => {
    expect(resolveSiteUrlForAuth('not a url !!!')).toBe('not a url !!!')
  })

  it('returns empty string for undefined', () => {
    expect(resolveSiteUrlForAuth(undefined)).toBe('')
  })
})

// --- isXCookieProfile ---
const makeAuth = (overrides: Partial<AuthConfig>): AuthConfig => ({
  id: 'test-id',
  site_url: 'https://x.com',
  auth_type: 'cookie',
  is_shared: false,
  status: 'active',
  login_selectors: {},
  has_credentials: true,
  bound_source_count: 0,
  created_at: '',
  updated_at: '',
  ...overrides,
})

describe('isXCookieProfile', () => {
  it('returns true for x.com cookie config', () => {
    expect(isXCookieProfile(makeAuth({ site_url: 'https://x.com', auth_type: 'cookie' }))).toBe(true)
  })

  it('returns true for twitter.com cookie config', () => {
    expect(isXCookieProfile(makeAuth({ site_url: 'https://twitter.com', auth_type: 'cookie' }))).toBe(true)
  })

  it('returns false for non-cookie auth_type', () => {
    expect(isXCookieProfile(makeAuth({ site_url: 'https://x.com', auth_type: 'password' }))).toBe(false)
  })

  it('returns false for unrelated site', () => {
    expect(isXCookieProfile(makeAuth({ site_url: 'https://example.com', auth_type: 'cookie' }))).toBe(false)
  })
})

// --- getAuthConfigDisplayName ---
describe('getAuthConfigDisplayName', () => {
  it('returns name when set', () => {
    expect(getAuthConfigDisplayName(makeAuth({ name: 'My Profile' }))).toBe('My Profile')
  })

  it('generates fallback from site_url and id prefix', () => {
    const cfg = makeAuth({ name: undefined, site_url: 'https://x.com', id: 'abcdefgh-1234' })
    expect(getAuthConfigDisplayName(cfg)).toMatch(/x\.com/)
    expect(getAuthConfigDisplayName(cfg)).toMatch(/abcdefgh/)
  })

  it('uses 凭证 as host fallback when site_url is empty', () => {
    const cfg = makeAuth({ name: undefined, site_url: '', id: 'abcdefgh-1234' })
    expect(getAuthConfigDisplayName(cfg)).toContain('凭证')
  })
})

// --- getDefaultSharedXAuthConfigId ---
describe('getDefaultSharedXAuthConfigId', () => {
  it('returns undefined for empty array', () => {
    expect(getDefaultSharedXAuthConfigId([])).toBeUndefined()
  })

  it('returns the id of the first config', () => {
    const cfg = makeAuth({ id: 'first-id' })
    expect(getDefaultSharedXAuthConfigId([cfg])).toBe('first-id')
  })
})
