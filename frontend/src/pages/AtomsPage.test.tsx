import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AtomsPage from './AtomsPage'

const { mockListAtoms, mockUpdateSettings, mockGetFeatures } = vi.hoisted(() => ({
  mockListAtoms: vi.fn(),
  mockUpdateSettings: vi.fn(),
  mockGetFeatures: vi.fn(),
}))

vi.mock('../services/atoms', () => ({
  atomsApi: {
    list: mockListAtoms,
    get: vi.fn(),
    stats: vi.fn(),
    update: vi.fn(),
    verify: vi.fn(),
    atomizeContent: vi.fn(),
    listRelations: vi.fn(),
    createRelation: vi.fn(),
    verifyRelation: vi.fn(),
    deleteRelation: vi.fn(),
  },
}))

vi.mock('../services/configs', () => ({
  configsApi: {
    updateSettings: mockUpdateSettings,
  },
}))

vi.mock('../services/system', () => ({
  systemApi: {
    getFeatures: mockGetFeatures,
  },
}))

function renderAtomsPage(queryClient: QueryClient) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AtomsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AtomsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('updates the shared system-settings cache after enabling atoms', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          staleTime: 1000 * 60 * 5,
        },
      },
    })
    queryClient.setQueryData(['system-settings'], {
      atoms_enabled: false,
      atoms_relations_enabled: false,
    })

    const updatedSettings = {
      atoms_enabled: true,
      atoms_relations_enabled: false,
    }
    mockGetFeatures
      .mockResolvedValueOnce({
        atoms_enabled: false,
        atoms_relations_enabled: false,
      })
      .mockResolvedValueOnce({
        atoms_enabled: true,
        atoms_relations_enabled: false,
      })
    mockUpdateSettings.mockResolvedValue(updatedSettings)
    mockListAtoms.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
      total_pages: 0,
    })

    renderAtomsPage(queryClient)

    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '启用原子库' }))

    await waitFor(() => {
      expect(mockUpdateSettings).toHaveBeenCalledWith({ atoms_enabled: true })
      expect(queryClient.getQueryData(['system-settings'])).toEqual(updatedSettings)
    })
  })
})
