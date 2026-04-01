import { describe, expect, it } from 'vitest'

import { detectSourceType, parseCSV, parseUrlLines } from './importUtils'

describe('importUtils', () => {
  it('detects supported source types from URLs', () => {
    expect(detectSourceType('https://www.youtube.com/@openai')).toBe('youtube')
    expect(detectSourceType('https://x.com/openai')).toBe('x')
    expect(detectSourceType('https://example.com/feed.xml')).toBe('rss')
    expect(detectSourceType('https://podcasts.apple.com/podcast/demo')).toBe('website')
    expect(detectSourceType('https://example.com/blog')).toBe('website')
  })

  it('parses deduplicated URL lines', () => {
    expect(parseUrlLines('https://a.test\n\nhttps://b.test\nhttps://a.test')).toEqual([
      'https://a.test',
      'https://b.test',
    ])
  })

  it('parses csv rows with quoted commas', () => {
    const csv = 'name,description,url\n"Tech, Daily","AI, chips","https://example.com"\n'
    expect(parseCSV(csv)).toEqual([
      {
        name: 'Tech, Daily',
        description: 'AI, chips',
        url: 'https://example.com',
      },
    ])
  })
})
