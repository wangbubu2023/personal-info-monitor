import { describe, expect, it } from 'vitest'

import type { Content, Digest } from '../../types'
import { contentToDigestItem, getDashboardCategoryCount, getDashboardItems } from './dashboardUtils'

const digestFixture: Digest = {
  date: '2026-03-31',
  total_items: 3,
  categories: {
    websites: {
      count: 1,
      items: [
        {
          id: 'w-1',
          source_name: 'Website',
          title: 'Website item',
          url: 'https://website.example.com',
          publish_time: '2026-03-31T03:00:00',
          fetched_at: '2026-03-31T03:10:00',
          read_status: false,
          favorited: false,
          keyword_matches: [],
          metadata: {},
        },
      ],
    },
    x_accounts: {
      count: 1,
      items: [
        {
          id: 'x-1',
          source_name: 'X',
          title: 'Tweet item',
          url: 'https://x.example.com',
          publish_time: '2026-03-31T05:00:00',
          fetched_at: '2026-03-31T05:05:00',
          read_status: false,
          favorited: false,
          keyword_matches: [],
          metadata: {},
        },
      ],
    },
    youtube: {
      count: 1,
      items: [
        {
          id: 'y-1',
          source_name: 'YouTube',
          title: 'Video item',
          url: 'https://youtube.example.com',
          publish_time: '2026-03-31T04:00:00',
          fetched_at: '2026-03-31T04:20:00',
          read_status: false,
          favorited: true,
          keyword_matches: [],
          metadata: {},
        },
      ],
    },
    podcasts: {
      count: 0,
      items: [],
    },
  },
}

describe('dashboardUtils', () => {
  it('sorts all dashboard items by publish time descending', () => {
    const items = getDashboardItems(digestFixture, 'all')
    expect(items.map((item) => item.id)).toEqual(['x-1', 'y-1', 'w-1'])
  })

  it('returns category counts including the synthetic all bucket', () => {
    expect(getDashboardCategoryCount(digestFixture, 'all')).toBe(3)
    expect(getDashboardCategoryCount(digestFixture, 'youtube')).toBe(1)
    expect(getDashboardCategoryCount(digestFixture, 'podcasts')).toBe(0)
  })

  it('converts content rows into digest items for reuse in dashboard views', () => {
    const content: Content = {
      id: 'c-1',
      source_id: 's-1',
      title: 'Converted',
      translated_title: '已转换',
      summary: 'Summary',
      translated_summary: '摘要',
      original_url: 'https://content.example.com',
      content_type: 'website',
      publish_time: '2026-03-31T01:00:00',
      read_status: true,
      favorited: false,
      archived: false,
      keyword_matches: [],
      metadata: { author: 'PIM' },
      fetched_at: '2026-03-31T01:05:00',
      created_at: '2026-03-31T01:05:00',
      updated_at: '2026-03-31T01:05:00',
      source_name: 'Source',
    }

    expect(contentToDigestItem(content)).toEqual({
      id: 'c-1',
      source_name: 'Source',
      title: 'Converted',
      translated_title: '已转换',
      summary: 'Summary',
      translated_summary: '摘要',
      url: 'https://content.example.com',
      publish_time: '2026-03-31T01:00:00',
      fetched_at: '2026-03-31T01:05:00',
      read_status: true,
      favorited: false,
      keyword_matches: [],
      metadata: { author: 'PIM' },
    })
  })
})
