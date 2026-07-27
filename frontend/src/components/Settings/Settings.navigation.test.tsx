import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../../config/features', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../config/features')>()),
  KEYWORD_MONITORING_ENABLED: true,
  SCORE_LAB_BUILD_ENABLED: false,
}))

vi.mock('../SourceList/SourceManager', () => ({
  default: () => <div>Source Manager</div>,
}))

vi.mock('./KeywordsTab', () => ({
  default: () => <div data-testid="mock-keywords-tab">Keyword Manager</div>,
}))

const LocationProbe = () => {
  const location = useLocation()
  return <div data-testid="location-search">{location.search}</div>
}

import Settings from './Settings'

describe('Settings navigation', () => {
  it('opens the keywords tab when its button is clicked', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/settings']}>
          <Settings />
          <LocationProbe />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await userEvent.click(screen.getByRole('button', { name: '关键词' }))

    expect(await screen.findByTestId('mock-keywords-tab')).toBeTruthy()
    expect(screen.getByTestId('settings-tab-description').textContent).toContain('为特定主题设置提醒与过滤。')
    expect(screen.getByTestId('location-search').textContent).toContain('?tab=keywords')
  })
})
