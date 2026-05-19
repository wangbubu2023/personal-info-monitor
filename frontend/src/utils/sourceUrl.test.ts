import { describe, expect, it } from 'vitest'
import { normalizeSourceUrl, parseSourceUrlInput, validateSourceUrlInput } from './sourceUrl'

describe('normalizeSourceUrl', () => {
  it('prepends https when scheme omitted', () => {
    expect(normalizeSourceUrl('www.bbc.com/zhongwen/simp')).toBe(
      'https://www.bbc.com/zhongwen/simp',
    )
  })

  it('preserves explicit scheme', () => {
    expect(normalizeSourceUrl('http://example.com')).toBe('http://example.com')
  })
})

describe('parseSourceUrlInput', () => {
  it('rejects unparseable input', () => {
    expect(parseSourceUrlInput('not a url !!!')).toBeNull()
  })

  it('accepts host without scheme', () => {
    expect(parseSourceUrlInput('www.bbc.com/zhongwen/simp')).toBe(
      'https://www.bbc.com/zhongwen/simp',
    )
  })
})

describe('validateSourceUrlInput', () => {
  it('returns Chinese message for invalid url', () => {
    expect(validateSourceUrlInput('@@@')).toMatch(/格式无法解析/)
  })
})
