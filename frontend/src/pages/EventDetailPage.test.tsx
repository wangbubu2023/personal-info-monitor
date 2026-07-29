import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import EventDetailPage from './EventDetailPage'

const { mockGetEventDetail, mockMarkEventSeen, mockSubmitEventFeedback, mockUpdateEventState } = vi.hoisted(() => ({
  mockGetEventDetail: vi.fn(),
  mockMarkEventSeen: vi.fn(),
  mockSubmitEventFeedback: vi.fn(),
  mockUpdateEventState: vi.fn(),
}))

vi.mock('../services/digest', async () => {
  const actual = await vi.importActual<typeof import('../services/digest')>('../services/digest')
  return {
    ...actual,
    digestApi: {
      getEventDetail: mockGetEventDetail,
      markEventSeen: mockMarkEventSeen,
      submitEventFeedback: mockSubmitEventFeedback,
      updateEventState: mockUpdateEventState,
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
    mockMarkEventSeen.mockResolvedValue({ target_type: 'event', target_id: 'event-1', last_seen_version: 2, saved: false, read_later: false, hidden: false })
    mockSubmitEventFeedback.mockResolvedValue({ type: 'event_wrong_merge' })
    mockUpdateEventState.mockResolvedValue({ target_type: 'event', target_id: 'event-1', last_seen_version: 0, saved: true, read_later: false, hidden: false })
    mockGetEventDetail.mockResolvedValue({
      event_id: 'event-1',
      event_key: 'launch-v4',
      title: '模型公司发布新版路线图',
      current_conclusion: '官方发布新路线图，分析师补充影响。',
      why_matters: '已有多个独立来源互相确认。',
      source_names: ['Official', 'Analyst'],
      independent_source_count: 2,
      updated_at: '2026-07-11T09:00:00Z',
      latest_version: 2,
      user_seen_version: 1,
      has_updates: true,
      saved: false,
      read_later: false,
      hidden: false,
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
      snapshots: [{ version: 2, title: '模型公司发布新版路线图', what_changed: '新增分析师解读。', is_seen: false }],
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
    expect(screen.getByText('事件版本 v2')).toBeTruthy()
    expect(screen.getByText('当前版本')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /标记已读/ })).toBeNull()
    expect(screen.getByRole('button', { name: /^收藏$/ })).toBeTruthy()
    expect(screen.getByText('独立验证')).toBeTruthy()
    expect(screen.getByText('观点 / 关联讨论')).toBeTruthy()
    expect(screen.getByRole('button', { name: /误合/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /漏合/ })).toBeTruthy()
  })

  it('loads the full timeline only after an explicit user action', async () => {
    const timeline = Array.from({ length: 5 }, (_, index) => ({
      content_id: `content-${index}`,
      title: `Report ${index}`,
      summary: `Summary ${index}`,
      source_name: 'Official',
      url: `https://example.com/${index}`,
      role: index === 4 ? 'primary' : 'supporting',
      publish_time: `2026-07-11T${String(8 + index).padStart(2, '0')}:00:00Z`,
    }))
    mockGetEventDetail.mockImplementation(async (_eventId: string, fullReports = false) => ({
      event_id: 'event-1',
      event_key: 'launch-v4',
      title: 'Curated boundary',
      current_conclusion: 'Current conclusion',
      source_names: ['Official'],
      independent_source_count: 1,
      latest_version: 1,
      user_seen_version: 0,
      has_updates: true,
      saved: false,
      read_later: false,
      hidden: false,
      timeline: fullReports ? timeline : timeline.slice(2),
      snapshots: [],
      primary_reports: [],
      independent_verification: [],
      related_discussions: [],
      feedback: [],
      extra: { view_mode: fullReports ? 'full' : 'curated', report_count: 5 },
    }))

    renderEventDetail()

    const expand = await screen.findByRole('button', { name: '查看全部 5 条' })
    expect(screen.queryByText('Report 0')).toBeNull()
    fireEvent.click(expand)

    expect(await screen.findByText('Report 0')).toBeTruthy()
    expect(mockGetEventDetail).toHaveBeenLastCalledWith('event-1', true)
    expect(screen.getByRole('button', { name: '收起精选' })).toBeTruthy()
  })

})
