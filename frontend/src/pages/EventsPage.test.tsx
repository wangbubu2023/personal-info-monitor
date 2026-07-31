import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import EventsPage from './EventsPage'

const { mockGetEventFeed } = vi.hoisted(() => ({
  mockGetEventFeed: vi.fn(),
}))

vi.mock('../services/digest', async () => {
  const actual = await vi.importActual<typeof import('../services/digest')>('../services/digest')
  return {
    ...actual,
    digestApi: {
      ...actual.digestApi,
      getEventFeed: mockGetEventFeed,
    },
  }
})

function renderEventsPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <EventsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('EventsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetEventFeed.mockResolvedValue({
      total: 1,
      hours: 168,
      items: [{
        event_id: 'event-visible',
        event_key: 'event:visible',
        title: '未达到重点门槛但已经形成的事件',
        summary: '单一来源事件也能进入事件消费流程。',
        independent_source_count: 1,
        source_names: ['Original Source'],
        importance_score: 45,
        updated_at: '2026-07-30T10:00:00Z',
      }],
    })
  })

  it('shows recent events independently of the highlights gate', async () => {
    renderEventsPage()

    expect(await screen.findByText('未达到重点门槛但已经形成的事件')).toBeTruthy()
    expect(screen.getByText('已显示 1 / 共 1 个事件')).toBeTruthy()
    expect(screen.getByText('1 个独立来源')).toBeTruthy()
    expect(screen.getByRole('link', { name: /未达到重点门槛/ }).getAttribute('href')).toBe('/events/event-visible')
  })
})
