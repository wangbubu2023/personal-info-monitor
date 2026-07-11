import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import EventDetailPage from './EventDetailPage'

const { mockGetEventDetail, mockSubmitEventFeedback } = vi.hoisted(() => ({
  mockGetEventDetail: vi.fn(),
  mockSubmitEventFeedback: vi.fn(),
}))

vi.mock('../services/digest', async () => {
  const actual = await vi.importActual<typeof import('../services/digest')>('../services/digest')
  return {
    ...actual,
    digestApi: {
      getEventDetail: mockGetEventDetail,
      submitEventFeedback: mockSubmitEventFeedback,
    },
  }
})

function renderEventDetail() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/events/event-1']}>
        <Routes>
          <Route path="/events/:eventId" element={<EventDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('EventDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSubmitEventFeedback.mockResolvedValue({ type: 'event_wrong_merge' })
    mockGetEventDetail.mockResolvedValue({
      event_id: 'event-1',
      event_key: 'launch-v4',
      title: '模型公司发布新版路线图',
      current_conclusion: '官方发布新路线图，分析师补充影响。',
      why_matters: '已有多个独立来源互相确认。',
      source_names: ['Official', 'Analyst'],
      independent_source_count: 2,
      updated_at: '2026-07-11T09:00:00Z',
      timeline: [
        {
          content_id: 'content-1',
          title: '官方发布路线图',
          summary: '官方版本。',
          source_name: 'Official',
          url: 'https://example.com/official',
          role: 'supporting',
          publish_time: '2026-07-11T08:00:00Z',
        },
        {
          content_id: 'content-2',
          title: '分析师解读路线图',
          summary: '分析版本。',
          source_name: 'Analyst',
          url: 'https://example.com/analyst',
          role: 'primary',
          publish_time: '2026-07-11T09:00:00Z',
        },
      ],
      snapshots: [{ version: 1, title: '模型公司发布新版路线图', what_changed: '新增分析师解读。' }],
      primary_reports: [],
      independent_verification: [{ key: 'Official', title: 'Official', content_ids: ['content-1'] }],
      related_discussions: [{ key: 'supporting', title: '关联讨论', content_ids: ['content-1'] }],
      feedback: [],
    })
  })

  it('renders conclusion, timeline, snapshots, and feedback controls', async () => {
    renderEventDetail()

    expect(await screen.findByTestId('event-detail-page')).toBeTruthy()
    expect(screen.getByText('官方发布新路线图，分析师补充影响。')).toBeTruthy()
    expect(screen.getByText('官方发布路线图')).toBeTruthy()
    expect(screen.getByText('分析师解读路线图')).toBeTruthy()
    expect(screen.getByText('新增分析师解读。')).toBeTruthy()
    expect(screen.getByText('独立验证')).toBeTruthy()
    expect(screen.getByText('观点 / 关联讨论')).toBeTruthy()
    expect(screen.getByRole('button', { name: /误合/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /漏合/ })).toBeTruthy()
  })
})
