import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi, beforeAll, beforeEach } from 'vitest'

import KeywordsTab from './KeywordsTab'

const { mockList, mockCreateBatch, mockUpdateBatch, mockUpdate, mockDelete } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockCreateBatch: vi.fn(),
  mockUpdateBatch: vi.fn(),
  mockUpdate: vi.fn(),
  mockDelete: vi.fn(),
}))

vi.mock('../../services/keywords', () => ({
  keywordsApi: {
    list: mockList,
    createBatch: mockCreateBatch,
    updateBatch: mockUpdateBatch,
    update: mockUpdate,
    delete: mockDelete,
  },
}))

vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd')
  return {
    ...actual,
    message: {
      success: vi.fn(),
      error: vi.fn(),
    },
  }
})

beforeEach(() => {
  vi.clearAllMocks()
})

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })

  window.getComputedStyle = vi.fn().mockImplementation(() => ({
    getPropertyValue: vi.fn(() => ''),
  })) as typeof window.getComputedStyle
})

function renderKeywordsTab() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <KeywordsTab />
    </QueryClientProvider>,
  )
}

describe('KeywordsTab', () => {
  it('PATCH 编辑时关闭「合并自动翻译」必须发送 include_auto_equivalent_terms: false', async () => {
    mockList.mockResolvedValue({
      items: [
        {
          id: 'kw-1',
          keyword: 'openclaw',
          description: undefined,
          match_type: 'contains',
          match_scope: 'title_content',
          case_sensitive: false,
          manual_equivalent_terms: [],
          include_auto_equivalent_terms: true,
          notify: false,
          notify_email: false,
          color: '#13c2c2',
          enabled: true,
          equivalent_terms: ['开爪'],
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    })
    mockUpdate.mockResolvedValue({
      id: 'kw-1',
      keyword: 'openclaw',
      match_type: 'contains',
      match_scope: 'title_content',
      case_sensitive: false,
      manual_equivalent_terms: [],
      include_auto_equivalent_terms: false,
      equivalent_terms: [],
      notify: false,
      notify_email: false,
      color: '#13c2c2',
      enabled: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    })

    renderKeywordsTab()

    const user = userEvent.setup()
    await screen.findByText('openclaw')
    await user.click(screen.getByRole('button', { name: /编辑/ }))

    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByText('编辑搜索词')
    const switches = within(dialog).getAllByRole('switch')
    // 表单顺序：合并自动翻译 → 启用（未展示通知开关，默认关闭）
    await user.click(switches[0])

    // Ant Design 在部分环境下会把「更新」拆成带空格的 accessible name，故用 submit + 宽松匹配
    await user.click(within(dialog).getByRole('button', { name: /更\s*新/ }))

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalled()
      expect(mockUpdate.mock.calls[0][1]).toMatchObject({
        include_auto_equivalent_terms: false,
      })
    })
  })

  it('submits batch keywords from newline-delimited input', async () => {
    mockList.mockResolvedValue({ items: [], total: 0 })
    mockCreateBatch.mockResolvedValue({
      items: [],
      total: 2,
      skipped_keywords: [],
    })

    renderKeywordsTab()

    const user = userEvent.setup()
    const addButtons = await screen.findAllByRole('button', { name: /添加搜索词/ })
    const openButton =
      addButtons.find((b) => (b as HTMLButtonElement).className.includes('ant-btn-primary')) ?? addButtons[0]
    await user.click(openButton)
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('搜索词'), 'AI{enter}OpenAI')
    await user.click(within(dialog).getByRole('button', { name: /创\s*建/ }))

    await waitFor(() => {
      expect(mockCreateBatch).toHaveBeenCalled()
      expect(mockCreateBatch.mock.calls[0][0]).toMatchObject({
        keywords: ['AI', 'OpenAI'],
        match_type: 'contains',
        match_scope: 'title_content',
        case_sensitive: false,
        color: '#ff4d4f',
        notify: false,
        enabled: true,
        manual_equivalent_terms: [],
        include_auto_equivalent_terms: true,
      })
    })
  })
})
