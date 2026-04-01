import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from './api'
import { sourcesApi } from './sources'

vi.mock('./api', () => ({
  default: {
    get: vi.fn(),
  },
}))

describe('sourcesApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('caps page_size to the backend limit', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { items: [], total: 0, page: 1, page_size: 200, total_pages: 1 },
    })

    await sourcesApi.list({ page: 1, page_size: 1000 })

    expect(api.get).toHaveBeenCalledWith('/sources', {
      params: { page: 1, page_size: 200 },
    })
  })

  it('loads all source pages for the source library', async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce({
        data: { items: [{ id: '1', name: 'one' }], total: 3, page: 1, page_size: 200, total_pages: 2 },
      })
      .mockResolvedValueOnce({
        data: { items: [{ id: '2', name: 'two' }, { id: '3', name: 'three' }], total: 3, page: 2, page_size: 200, total_pages: 2 },
      })

    const items = await sourcesApi.listAll()

    expect(items).toHaveLength(3)
    expect(api.get).toHaveBeenNthCalledWith(1, '/sources', {
      params: { page: 1, page_size: 200 },
    })
    expect(api.get).toHaveBeenNthCalledWith(2, '/sources', {
      params: { page: 2, page_size: 200 },
    })
  })
})
