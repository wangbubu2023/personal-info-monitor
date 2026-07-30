import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ContentTagEditor from './ContentTagEditor'

const { mockSetTags } = vi.hoisted(() => ({
  mockSetTags: vi.fn(),
}))

vi.mock('../../services/contents', () => ({
  contentsApi: {
    setTags: mockSetTags,
  },
}))

describe('ContentTagEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSetTags.mockResolvedValue({ tags: ['macro_finance', 'markets'] })
  })

  it('shows current tags before offering an explicit adjustment', async () => {
    const user = userEvent.setup()
    render(
      <ContentTagEditor
        contentId="content-1"
        tags={['macro_finance']}
        editable
      />,
    )

    expect(screen.getByText('宏观金融')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '市场交易' })).toBeNull()

    await user.click(screen.getByRole('button', { name: '调整标签' }))
    await user.click(screen.getByRole('button', { name: '市场交易' }))
    await user.click(screen.getByRole('button', { name: '保存标签' }))

    expect(mockSetTags).toHaveBeenCalledWith(
      'content-1',
      ['macro_finance', 'markets'],
    )
  })
})
