import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DigestView from './DigestView'

const { mockGetHourlyDigests, mockGetHourlyDigestDetail } = vi.hoisted(() => ({
  mockGetHourlyDigests: vi.fn(),
  mockGetHourlyDigestDetail: vi.fn(),
}))

vi.mock('../../services/digest', async () => {
  const actual = await vi.importActual<typeof import('../../services/digest')>('../../services/digest')
  return {
    ...actual,
    digestApi: {
      getHourlyDigests: mockGetHourlyDigests,
      getHourlyDigestDetail: mockGetHourlyDigestDetail,
    },
  }
})

function renderDigestView() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DigestView />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DigestView hourly digest list', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetHourlyDigests.mockResolvedValue([
      { hour: 9, title: '7 月 27 日 9 时简报', content_count: 3, sources: { websites: 3, x: 0, youtube: 0, podcasts: 0 } },
    ])
    mockGetHourlyDigestDetail.mockResolvedValue({
      hour: 9,
      date: '2026-07-27',
      title: '7 月 27 日 9 时简报',
      summary: '## 重点摘要\n\n这是本小时的简报正文。',
      content_count: 3,
      sources: ['Source A', 'Source B'],
      generated_at: '2026-07-27T01:05:00Z',
      event_items: [
        {
          content_id: 'event-content-1',
          event_id: 'event-1',
          title: '不应显示的事件卡片',
          source_name: 'Source A',
          url: 'https://example.com/event',
        },
      ],
      items: [
        {
          id: 'material-1',
          source_id: 'source-1',
          source_name: 'Source A',
          title: '不应显示的入选素材',
          url: 'https://example.com/material',
          read_status: false,
          favorited: false,
          keyword_matches: [],
          metadata: {},
        },
      ],
    })
  })

  it('keeps the page focused on hourly briefs instead of repeating today highlights', async () => {
    renderDigestView()

    expect(await screen.findByTestId('digest-hour-card-9')).toBeTruthy()
    expect(screen.getAllByText('时段简报')).toHaveLength(2)
    expect(screen.queryByText('收录素材')).toBeNull()
    expect(screen.queryByText('今日重点')).toBeNull()
  })

  it('shows only the brief body in hourly detail', async () => {
    const user = userEvent.setup()
    renderDigestView()

    await user.click(await screen.findByTestId('digest-hour-card-9'))

    expect(await screen.findByTestId('digest-detail')).toBeTruthy()
    expect(screen.getByText('这是本小时的简报正文。')).toBeTruthy()
    expect(screen.queryByText('事件卡片')).toBeNull()
    expect(screen.queryByText('不应显示的事件卡片')).toBeNull()
    expect(screen.queryByText('入选素材')).toBeNull()
    expect(screen.queryByText('不应显示的入选素材')).toBeNull()
    expect(screen.queryByText('事件数')).toBeNull()
    expect(screen.queryByText('输入素材')).toBeNull()
    expect(screen.queryByText('主要来源')).toBeNull()
  })
})
