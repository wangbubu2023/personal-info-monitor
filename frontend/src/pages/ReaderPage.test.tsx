import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ReaderPage from './ReaderPage'

const { mockUseReader } = vi.hoisted(() => ({
  mockUseReader: vi.fn(),
}))

vi.mock('../hooks/useReader', () => ({
  useReader: mockUseReader,
}))

function renderReaderPage() {
  return render(
    <MemoryRouter initialEntries={['/reader/content-1']}>
      <Routes>
        <Route path="/reader/:id" element={<ReaderPage />} />
        <Route path="/timeline" element={<div>全部动态</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ReaderPage', () => {
  const setLiked = vi.fn()
  const hide = vi.fn()

  afterEach(() => {
    cleanup()
  })

  beforeEach(() => {
    vi.clearAllMocks()
    mockUseReader.mockReturnValue({
      data: {
        id: 'content-1',
        source_id: 'source-1',
        source_name: '纽约时报中文版',
        title: 'Original title',
        original_url: 'https://cn.nytimes.com/world/story',
        read_status: false,
        favorited: false,
        body_raw: '',
        body_zh: '',
        clean_html: '',
        blocks: [],
      },
      loading: false,
      error: null,
      displayTitle: 'Structured reader',
      displayParagraphs: [],
      displayBlocks: [
        { type: 'heading', level: 2, text: 'Structured Heading' },
        { type: 'paragraph', text: '<script>evil()</script>' },
        { type: 'image', src: 'https://example.com/diagram.png', alt: 'Diagram', caption: 'System diagram' },
        { type: 'quote', text: 'Quoted context' },
        { type: 'code', language: 'ts', text: 'const answer = 42' },
        { type: 'footnote', marker: '1', text: 'A careful source note' },
        { type: 'link', href: 'https://example.com/read-more', text: 'Read more' },
        { type: 'link', href: 'javascript:alert(1)', text: 'Unsafe link' },
        { type: 'image', src: 'javascript:alert(1)', alt: 'Unsafe image' },
      ],
      stream: {
        chunks: [],
        total: 0,
        loading: false,
        finished: false,
        succeeded: false,
        hint: null,
      },
      setLiked,
      hide,
    })
  })

  it('renders whitelisted reader blocks without injecting html', () => {
    const { container } = renderReaderPage()

    expect(screen.getByRole('heading', { name: 'Structured Heading' }).tagName).toBe('H2')
    expect(screen.getByText('<script>evil()</script>')).toBeTruthy()
    expect(container.querySelector('script')).toBeNull()

    const image = screen.getByAltText('Diagram') as HTMLImageElement
    expect(image.tagName).toBe('IMG')
    expect(image.getAttribute('src')).toContain('https://example.com/diagram.png')
    expect(screen.getByText('System diagram')).toBeTruthy()
    expect(screen.queryByAltText('Unsafe image')).toBeNull()

    expect(screen.getByText('Quoted context').tagName).toBe('BLOCKQUOTE')
    expect(container.querySelector('pre code')?.textContent).toBe('const answer = 42')
    expect(screen.getByText('A careful source note')).toBeTruthy()

    const link = screen.getByRole('link', { name: /Read more/ }) as HTMLAnchorElement
    expect(link.href).toBe('https://example.com/read-more')
    expect(screen.queryByText('Unsafe link')).toBeNull()
  })

  it('shows bounded Web Clean diagnostics when available', () => {
    mockUseReader.mockReturnValue({
      ...mockUseReader(),
      data: {
        ...mockUseReader().data,
        web_clean: {
          extraction_method: 'template_selector',
          template_id: 'example-v1',
          quality_status: 'good',
          quality_score: 0.91,
          text_chars: 1234,
          paragraph_count: 8,
          boilerplate_ratio: 0.08,
          link_density: 0.12,
          shadow: true,
          shadow_diff: { old_chars: 900, new_chars: 1234, char_delta: 334 },
          rejected_reasons: ['listing_like'],
          template_validation_errors: ['bad selector'],
          shadow_materialized_count: 2,
          shadow_timeout: true,
          truncated: false,
        },
      },
    })

    renderReaderPage()

    expect(screen.getByTestId('web-clean-diagnostic')).toBeTruthy()
    expect(screen.getByText('网页清洗诊断')).toBeTruthy()
    expect(screen.getByText(/方法：template_selector/)).toBeTruthy()
    expect(screen.getByText(/旧\/新正文：900 → 1234/)).toBeTruthy()
    expect(screen.getByText(/候选拒绝：listing_like/)).toBeTruthy()
    expect(screen.getByText(/模板错误：bad selector/)).toBeTruthy()
  })

  it('uses paid-source layout profiles', () => {
    renderReaderPage()

    expect(screen.getByTestId('reader-iframe').closest('article')?.getAttribute('data-reader-layout')).toBe('nyt-cn')
  })

  it('handles reader keyboard actions', async () => {
    const user = userEvent.setup()
    renderReaderPage()

    await user.keyboard('l')
    expect(setLiked).toHaveBeenCalledWith(true)

    await user.keyboard('h')
    expect(hide).toHaveBeenCalledTimes(1)
  })

  it('labels positive feedback as important', () => {
    renderReaderPage()

    expect(screen.getByRole('button', { name: '重要' })).toBeTruthy()
  })

  it('shows toolbar shortcut hints', () => {
    renderReaderPage()

    for (const key of ['K', 'J', 'L', 'H']) {
      expect(screen.getByText(key)).toBeTruthy()
    }
  })

  it('returns to the all-activity timeline by default', () => {
    renderReaderPage()

    expect(screen.getByRole('link', { name: '返回' }).getAttribute('href')).toBe('/timeline')
  })

  it('hides via toolbar button and records negative feedback intent', async () => {
    const user = userEvent.setup()
    renderReaderPage()

    await user.click(screen.getByRole('button', { name: '不重要' }))
    expect(hide).toHaveBeenCalledTimes(1)
  })

  it('shows important and not-important side by side without markdown export', () => {
    const { container } = renderReaderPage()

    const important = screen.getByRole('button', { name: '重要' })
    const notImportant = screen.getByRole('button', { name: '不重要' })

    expect(important.parentElement).toBe(notImportant.parentElement)
    expect(important.parentElement?.classList.contains('flex')).toBe(true)
    expect(screen.queryByRole('button', { name: '更多操作' })).toBeNull()
    expect(screen.queryByText('导出 Markdown')).toBeNull()
    expect(container.textContent).not.toContain('导出 Markdown')
  })
})
