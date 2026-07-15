import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DigestView from './DigestView'

const { mockGetHourlyDigests } = vi.hoisted(() => ({
  mockGetHourlyDigests: vi.fn(),
}))

vi.mock('../../services/digest', async () => {
  const actual = await vi.importActual<typeof import('../../services/digest')>('../../services/digest')
  return {
    ...actual,
    digestApi: {
      getHourlyDigests: mockGetHourlyDigests,
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

describe('DigestView hourly digest list', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetHourlyDigests.mockResolvedValue([
      { hour: 9, content_count: 3, sources: { websites: 3, x: 0, youtube: 0, podcasts: 0 } },
    ])
  })

  it('keeps the page focused on hourly briefs instead of repeating today highlights', async () => {
    renderDigestView()

    expect(await screen.findByTestId('digest-hour-card-9')).toBeTruthy()
    expect(screen.getAllByText('时段简报')).toHaveLength(2)
    expect(screen.getByText('收录素材')).toBeTruthy()
    expect(screen.queryByText('今日重点')).toBeNull()
  })
})
