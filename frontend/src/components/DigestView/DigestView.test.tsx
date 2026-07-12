import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DigestView from './DigestView'

const { mockGetHourlyDigests, mockGetTodayHighlights } = vi.hoisted(() => ({
  mockGetHourlyDigests: vi.fn(),
  mockGetTodayHighlights: vi.fn(),
}))

vi.mock('../../services/digest', async () => {
  const actual = await vi.importActual<typeof import('../../services/digest')>('../../services/digest')
  return {
    ...actual,
    digestApi: {
      getHourlyDigests: mockGetHourlyDigests,
      getTodayHighlights: mockGetTodayHighlights,
      getHourlyDigestDetail: vi.fn(),
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

describe('DigestView today highlights', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetHourlyDigests.mockResolvedValue([
      { hour: 9, content_count: 3, sources: { websites: 3, x: 0, youtube: 0, podcasts: 0 } },
    ])
    mockGetTodayHighlights.mockResolvedValue({
      date: '2026-07-11',
      items: [
        {
          event_id: 'event-1',
          event_key: 'launch-v4',
          section: 'need_to_know',
          title: '模型公司发布新版路线图',
          why_matters: '已有多个独立来源互相确认。',
          what_changed: '官方路线图发布。',
          independent_source_count: 3,
          source_names: ['Official', 'Analyst'],
          importance_score: 88,
          updated_at: '2026-07-11T09:00:00Z',
          latest_version: 2,
          user_seen_version: 1,
          has_updates: true,
        },
      ],
    })
  })

  it('renders today highlights on digest page without changing timeline cards', async () => {
    renderDigestView()

    expect(await screen.findByTestId('today-highlights')).toBeTruthy()
    expect(screen.getByText('今日重点')).toBeTruthy()
    expect(screen.getByTestId('today-highlight-update-badge')).toBeTruthy()
    expect(screen.getByRole('link', { name: /模型公司发布新版路线图/ }).getAttribute('href')).toBe('/events/event-1')
    expect(screen.getByTestId('digest-hour-card-9')).toBeTruthy()
  })
})
