import { describe, expect, it } from 'vitest'

import type { Content, Digest } from '../../types'
import {
  buildDashboardSourcePath,
  buildDashboardHomePath,
  buildReaderPath,
  capDashboardListPreview,
  contentToDigestItem,
  digestSummaryPlain,
  getDigestItemFinalScore,
  getDigestItemFulltextStatusLabel,
  getDigestItemRecommendationReason,
  getDigestItemSourceStars,
  getDashboardCategoryCount,
  getDashboardItems,
  makeDigestBodyPreview,
} from './dashboardUtils'

const digestFixture: Digest = {
  date: '2026-03-31',
  total_items: 4,
  categories: {
    websites: {
      count: 1,
      items: [
        {
          id: 'w-1',
          source_name: 'Website',
          title: 'Website item',
          url: 'https://website.example.com',
          publish_time: '2018-06-01T12:00:00',
          fetched_at: '2026-03-31T06:00:00',
          read_status: false,
          favorited: false,
          keyword_matches: [],
          metadata: { final_score: 99 },
        },
      ],
    },
    rss: {
      count: 1,
      items: [
        {
          id: 'r-1',
          source_name: 'RSS',
          title: 'RSS item',
          url: 'https://rss.example.com/feed.xml',
          publish_time: '2026-03-31T04:30:00',
          fetched_at: '2026-03-31T04:35:00',
          read_status: false,
          favorited: false,
          keyword_matches: [],
          metadata: { final_score: 60 },
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
          metadata: { final_score: 70 },
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
          metadata: { article_score: 80 },
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
  it('sorts merged items by publish_time desc then fetched_at', () => {
    const items = getDashboardItems(digestFixture, 'all')
    expect(items.map((item) => item.id)).toEqual(['x-1', 'r-1', 'y-1', 'w-1'])
  })

  it('sorts obvious future publish times by fetched_at fallback', () => {
    const digest: Digest = {
      ...digestFixture,
      total_items: 2,
      categories: {
        ...digestFixture.categories,
        websites: {
          count: 2,
          items: [
            {
              id: 'nyt-bad-time',
              source_name: '纽约时报中文版',
              title: 'Future-shifted sitemap item',
              url: 'https://cn.nytimes.com/world/item',
              publish_time: '2026-07-08T10:12:00',
              fetched_at: '2026-07-08T02:12:00',
              read_status: false,
              favorited: false,
              keyword_matches: [],
              metadata: {},
            },
            {
              id: 'fresh-normal',
              source_name: 'Normal',
              title: 'Normal item',
              url: 'https://example.com/normal',
              publish_time: '2026-07-08T03:00:00',
              fetched_at: '2026-07-08T03:05:00',
              read_status: false,
              favorited: false,
              keyword_matches: [],
              metadata: {},
            },
          ],
        },
        rss: { count: 0, items: [] },
        x_accounts: { count: 0, items: [] },
        youtube: { count: 0, items: [] },
        podcasts: { count: 0, items: [] },
      },
    }

    const items = getDashboardItems(digest, 'websites')
    expect(items.map((item) => item.id)).toEqual(['fresh-normal', 'nyt-bad-time'])
  })

  it('sorts merged items by score desc when requested', () => {
    const items = getDashboardItems(digestFixture, 'all', 'score_desc')
    expect(items.map((item) => item.id)).toEqual(['w-1', 'y-1', 'x-1', 'r-1'])
  })

  it('returns category counts including the synthetic all bucket', () => {
    expect(getDashboardCategoryCount(digestFixture, 'all')).toBe(4)
    expect(getDashboardCategoryCount(digestFixture, 'rss')).toBe(1)
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
      source_id: 's-1',
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

describe('digestSummaryPlain', () => {
  it('strips tags so list preview is visible', () => {
    expect(digestSummaryPlain('<p>可见文字</p>')).toBe('可见文字')
    expect(digestSummaryPlain('  \n  ')).toBe('')
  })
})

describe('makeDigestBodyPreview', () => {
  it('strips HTML and truncates long plain text', () => {
    const long = '测'.repeat(400)
    const prev = makeDigestBodyPreview(`<p>${long}</p>`)
    expect(prev).toBeDefined()
    expect(prev!.endsWith('…')).toBe(true)
    expect(prev!.length).toBeLessThanOrEqual(285)
  })

  it('returns undefined when plain text too short', () => {
    expect(makeDigestBodyPreview('<p>短</p>')).toBeUndefined()
  })
})

describe('capDashboardListPreview', () => {
  it('truncates very long plain text like mistaken full article in summary', () => {
    const long = '文'.repeat(500)
    const out = capDashboardListPreview(long)
    expect(out.endsWith('…')).toBe(true)
    expect(out.length).toBeLessThanOrEqual(285)
  })

  it('keeps short text when below digest preview minimum', () => {
    expect(capDashboardListPreview('短')).toBe('短')
  })
})

describe('digest item quality metadata helpers', () => {
  it('normalizes score, source stars, and fulltext status labels for badges', () => {
    const item = {
      id: 'q-1',
      source_name: 'Quality',
      title: 'Quality item',
      url: 'https://quality.example.com',
      read_status: false,
      favorited: false,
      keyword_matches: [],
      metadata: {
        final_score: '86.4',
        source_stars: '3',
        fulltext_status: 'summary_only',
        recommendation_reason: {
          why_matters: '主题相关评分较高。',
          caveat: '需要交叉验证。',
          confidence: 0.83,
        },
      },
    }

    expect(getDigestItemFinalScore(item)).toBe(86.4)
    expect(getDigestItemSourceStars(item)).toBe(3)
    expect(getDigestItemFulltextStatusLabel(item)).toBe('摘要')
    expect(getDigestItemRecommendationReason(item)).toMatchObject({
      why_matters: '主题相关评分较高。',
      caveat: '需要交叉验证。',
      confidence: 0.83,
    })
  })
})

describe('buildReaderPath / buildDashboardHomePath', () => {
  it('阅读链接在非「全部」分类下附带 tab', () => {
    expect(buildReaderPath('x', { tab: 'rss' })).toBe('/reader/x?tab=rss')
    expect(buildReaderPath('x', { translate: true, tab: 'rss' })).toBe('/reader/x?translate=1&tab=rss')
  })

  it('「全部」不附带 tab', () => {
    expect(buildReaderPath('x', { tab: 'all' })).toBe('/reader/x')
  })

  it('搜索上下文附带 search，返回全部动态时优先恢复 search', () => {
    expect(buildReaderPath('x', { search: 'foo' })).toBe('/reader/x?search=foo')
    expect(buildDashboardHomePath('rss', 'foo')).toBe('/timeline?search=foo')
    expect(buildDashboardHomePath('rss', undefined)).toBe('/timeline?tab=rss')
  })

  it('信源上下文附带 source_id，阅读页返回时保留信源过滤', () => {
    expect(buildDashboardSourcePath('s-1', '36kr')).toBe('/timeline?source_id=s-1&source=36kr')
    expect(buildReaderPath('x', { sourceId: 's-1', sourceName: '36kr' })).toBe('/reader/x?source_id=s-1&source=36kr')
    expect(buildDashboardHomePath('rss', undefined, 's-1', '36kr')).toBe('/timeline?source_id=s-1&source=36kr')
    expect(buildDashboardHomePath('rss', 'ai', 's-1', '36kr')).toBe('/timeline?search=ai&source_id=s-1&source=36kr')
  })

  it('无筛选上下文时返回全部动态，而不是今日重点', () => {
    expect(buildDashboardHomePath()).toBe('/timeline')
    expect(buildDashboardSourcePath()).toBe('/timeline')
  })
})
