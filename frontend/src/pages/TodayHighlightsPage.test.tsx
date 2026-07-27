import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import TodayHighlightsPage from './TodayHighlightsPage'

const { mockGetTodayHighlights } = vi.hoisted(() => ({
  mockGetTodayHighlights: vi.fn(),
}))

vi.mock('../services/digest', async () => {
  const actual = await vi.importActual<typeof import('../services/digest')>('../services/digest')
  return {
    ...actual,
    digestApi: {
      ...actual.digestApi,
      getTodayHighlights: mockGetTodayHighlights,
    },
  }
})

function renderTodayHighlightsPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <TodayHighlightsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('TodayHighlightsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetTodayHighlights.mockResolvedValue({
      date: '2026-07-27',
      items: [
        {
          event_id: 'event-1',
          event_key: 'event:one',
          title: '滚动窗口内的聚合事件',
          why_matters: '多个独立来源确认，且热度超过阈值。',
          what_changed: '新的确认材料进入事件。',
          independent_source_count: 2,
          source_names: ['Official', 'Independent'],
          importance_score: 88,
          updated_at: '2026-07-27T01:00:00Z',
        },
      ],
    })
  })

  it('renders persisted event cards from the rolling 48-hour feed', async () => {
    renderTodayHighlightsPage()

    expect(await screen.findByText('滚动窗口内的聚合事件')).toBeTruthy()
    expect(screen.getByText('滚动 48 小时')).toBeTruthy()
    expect(screen.getByText('2 个独立来源')).toBeTruthy()
    expect(screen.getByRole('link', { name: /滚动窗口内的聚合事件/ }).getAttribute('href')).toBe('/events/event-1')
  })
})
