import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

// Partial mock: inherit real exports so newly added flags don't break the
// mock, but pin the flags this test asserts on to a known-off state.
vi.mock('../../config/features', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../config/features')>()),
  PODCAST_SOURCES_ENABLED: false,
  KEYWORD_MONITORING_ENABLED: false,
  SCORE_LAB_BUILD_ENABLED: false,
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

vi.mock('./MaintenanceTab', () => ({
  default: () => React.createElement('div', null, 'Maintenance'),
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
    expect(html).toContain('系统维护')
    expect(html).not.toContain('搜索词管理')
    expect(html).toContain('settings-page')
  })
})
