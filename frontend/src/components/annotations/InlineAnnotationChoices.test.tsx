import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import InlineAnnotationChoices from './InlineAnnotationChoices'

const { mockSubmitLabel } = vi.hoisted(() => ({
  mockSubmitLabel: vi.fn(),
}))

vi.mock('../../hooks/useRuntimeFeatures', () => ({
  useRuntimeFeatures: () => ({
    runtime_profile: 'development',
    development_mode: true,
    inline_annotations_enabled: true,
  }),
}))

vi.mock('../../services/annotations', () => ({
  annotationsApi: {
    submitLabel: mockSubmitLabel,
    getTarget: vi.fn().mockResolvedValue([]),
  },
}))

describe('InlineAnnotationChoices', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSubmitLabel.mockResolvedValue({ id: 'label-1' })
  })

  it('saves a choice without leaving the consumption flow', async () => {
    const user = userEvent.setup()
    render(
      <InlineAnnotationChoices
        taskType="content_value"
        targetType="content"
        targetId="content-1"
        label="顺手标"
        compact
        loadExisting={false}
        choices={[
          { value: 'must_see', label: '必看' },
          { value: 'noise', label: '噪音' },
        ]}
      />,
    )

    await user.click(screen.getByRole('button', { name: '顺手标：必看' }))

    expect(mockSubmitLabel).toHaveBeenCalledWith(expect.objectContaining({
      task_type: 'content_value',
      target_type: 'content',
      target_id: 'content-1',
      label_payload: { value: 'must_see' },
    }))
    expect(screen.getByRole('button', { name: '顺手标：必看' }).getAttribute('aria-pressed')).toBe('true')
  })
})
