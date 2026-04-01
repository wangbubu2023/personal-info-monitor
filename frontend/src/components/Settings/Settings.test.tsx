import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../../config/features', () => ({
  PODCAST_SOURCES_ENABLED: false,
  KEYWORD_MONITORING_ENABLED: false,
}))

vi.mock('../SourceList/SourceManager', () => ({
  default: () => React.createElement('div', { 'data-testid': 'mock-source-manager' }, 'Source Manager'),
}))

vi.mock('./APIKeysTab', () => ({
  default: () => React.createElement('div', null, 'API Keys'),
}))

vi.mock('./AIModelTab', () => ({
  default: () => React.createElement('div', null, 'AI Model'),
}))

import Settings from './Settings'

describe('Settings', () => {
  it('renders the settings header and default tabs', () => {
    const html = renderToStaticMarkup(React.createElement(Settings))

    expect(html).toContain('设置')
    expect(html).toContain('监控源管理')
    expect(html).toContain('采集凭证')
    expect(html).toContain('模型管理')
    expect(html).not.toContain('搜索词管理')
    expect(html).toContain('settings-page')
  })
})
