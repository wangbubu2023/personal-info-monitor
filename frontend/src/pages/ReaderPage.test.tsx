import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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
      </Routes>
    </MemoryRouter>,
  )
}

describe('ReaderPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseReader.mockReturnValue({
      data: {
        id: 'content-1',
        source_id: 'source-1',
        source_name: 'Example',
        title: 'Original title',
        original_url: 'https://example.com/story',
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

    const link = screen.getByRole('link', { name: /Read more/ }) as HTMLAnchorElement
    expect(link.href).toBe('https://example.com/read-more')
    expect(screen.queryByText('Unsafe link')).toBeNull()
  })
})
