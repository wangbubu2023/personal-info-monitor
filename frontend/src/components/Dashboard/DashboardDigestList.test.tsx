import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import DashboardDigestList from './DashboardDigestList'
import type { DigestItem } from '../../types'

vi.mock('../../services/contents', () => ({
  contentsApi: {
    markAsRead: vi.fn(async () => undefined),
    setFavorite: vi.fn(async (_id: string, favorited: boolean) => ({ favorited })),
    update: vi.fn(async () => ({})),
  },
}))

function item(id: string, title: string, readStatus: boolean): DigestItem {
  return {
    id,
    source_name: 'Example',
    title,
    summary: 'Summary text',
    url: `https://example.com/${id}`,
    read_status: readStatus,
    favorited: false,
    keyword_matches: [],
    metadata: { duplicate_group_id: 'event-1' },
  }
}

function renderList(items: DigestItem[]) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DashboardDigestList
          isLoading={false}
          items={items}
          rangeLabel="2026-07-07"
          activeTab="all"
          categories={[{ key: 'all', label: '全部', type: 'all' }]}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DashboardDigestList', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('collapses fully-read event groups and expands them on demand', async () => {
    const user = userEvent.setup()
    renderList([item('a', 'First item', true), item('b', 'Second item', true)])

    expect(screen.getByText(/已读事件簇/)).toBeTruthy()
    expect(screen.queryByText('Second item')).toBeNull()

    await user.click(screen.getByText(/已读事件簇/))
    expect(screen.getByText('Second item')).toBeTruthy()
  })

  it('shows list feedback actions', () => {
    renderList([{ ...item('a', 'First item', false), metadata: {} }])

    expect(screen.getByRole('button', { name: '标为已读' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '喜欢' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '不感兴趣' })).toBeTruthy()
  })
})
