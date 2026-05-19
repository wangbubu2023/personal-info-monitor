import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../../config/features', () => ({
  PODCAST_SOURCES_ENABLED: false,
  KEYWORD_MONITORING_ENABLED: false,
}))

vi.mock('../SourceList/SourceManager', () => ({
  default: () => React.createElement('div', { 'data-testid': 'mock-source-manager' }, 'Source Manager'),
}))

vi.mock('./CredentialsTab', () => ({
  default: () => React.createElement('div', null, 'Credentials'),
}))

vi.mock('./AIModelTab', () => ({
  default: () => React.createElement('div', null, 'AI Model'),
}))

vi.mock('./TaskPromptsTab', () => ({
  default: () => React.createElement('div', null, 'Task Prompts'),
}))

import Settings from './Settings'

describe('Settings', () => {
  it('renders the settings header and default tabs', () => {
    const html = renderToStaticMarkup(
      React.createElement(MemoryRouter, { initialEntries: ['/settings'] }, React.createElement(Settings)),
    )

    expect(html).toContain('系统设置')
    expect(html).toContain('监测源')
    expect(html).toContain('登录与凭据')
    expect(html).toContain('智能引擎')
    expect(html).toContain('任务提示')
    expect(html).not.toContain('搜索词管理')
    expect(html).toContain('settings-page')
  })
})
