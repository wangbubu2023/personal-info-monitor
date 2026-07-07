import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import DashboardDigestList from './DashboardDigestList'
import type { DigestItem } from '../../types'

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

describe('DashboardDigestList', () => {
  it('collapses fully-read event groups and expands them on demand', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <DashboardDigestList
          isLoading={false}
          items={[item('a', 'First item', true), item('b', 'Second item', true)]}
          rangeLabel="2026-07-07"
          activeTab="all"
          categories={[{ key: 'all', label: '全部', type: 'all' }]}
        />
      </MemoryRouter>,
    )

    expect(screen.getByText(/已读事件簇/)).toBeTruthy()
    expect(screen.queryByText('Second item')).toBeNull()

    await user.click(screen.getByText(/已读事件簇/))
    expect(screen.getByText('Second item')).toBeTruthy()
  })
})
