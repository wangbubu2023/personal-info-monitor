import React, { Suspense, lazy, useState } from 'react'
import { Spin } from 'antd'
import { KeyOutlined, RobotOutlined } from '@ant-design/icons'
import { KEYWORD_MONITORING_ENABLED } from '../../config/features'

const SourceManager = lazy(() => import('../SourceList/SourceManager'))
const APIKeysTab = lazy(() => import('./APIKeysTab'))
const AIModelTab = lazy(() => import('./AIModelTab'))

interface SettingsTabItem {
  key: string
  label: React.ReactNode
  content: React.ReactNode
}

const SettingsContentFallback: React.FC = () => (
  <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
    <Spin size="large" />
  </div>
)

const Settings: React.FC = () => {
  const [activeTab, setActiveTab] = useState('sources')
  const tabItems: SettingsTabItem[] = [
    { key: 'sources', label: '监控源管理', content: <SourceManager /> },
    { key: 'api-keys', label: <span><KeyOutlined /> 采集凭证</span>, content: <APIKeysTab /> },
    { key: 'ai-model', label: <span><RobotOutlined /> 模型管理</span>, content: <AIModelTab /> },
  ]
  if (KEYWORD_MONITORING_ENABLED) {
    const KeywordsTab = lazy(() => import('./KeywordsTab'))
    tabItems.push({ key: 'keywords', label: '搜索词管理', content: <KeywordsTab /> })
  }
  const activeItem = tabItems.find((item) => item.key === activeTab) || tabItems[0]

  return (
    <div style={{ backgroundColor: '#fff', minHeight: '100vh' }} data-testid="settings-page">
      <div style={{
        backgroundColor: '#f5f5f5',
        borderBottom: '1px solid #eee',
      }} data-testid="settings-header">
        <div style={{
          maxWidth: 1200,
          margin: '0 auto',
          padding: '16px 24px',
          display: 'flex',
          alignItems: 'baseline',
          gap: 12,
        }}>
          <h1
            data-testid="settings-header-title"
            style={{
              fontSize: 20,
              fontWeight: 500,
              color: '#333',
              margin: 0,
              lineHeight: 1.4,
            }}
          >
            设置
          </h1>
          <span style={{ color: '#ccc' }}>|</span>
          <span style={{
            margin: 0,
            fontSize: 13,
            color: '#999',
          }}>
            监控源、采集凭证与模型配置
          </span>
        </div>
      </div>

      <div style={{ borderBottom: '1px solid #eee', backgroundColor: '#fafafa' }} data-testid="settings-tabs">
        <div style={{ maxWidth: 1200, margin: '0 auto', padding: '0 24px', display: 'flex', gap: 0 }}>
          {tabItems.map((item) => (
            <button
              key={item.key}
              onClick={() => setActiveTab(item.key)}
              data-testid={`settings-tab-${item.key}`}
              style={{
                padding: '12px 20px',
                fontSize: 14,
                fontWeight: activeTab === item.key ? 600 : 400,
                color: activeTab === item.key ? '#6b7c3f' : '#666',
                backgroundColor: activeTab === item.key ? '#fff' : 'transparent',
                border: 'none',
                borderBottom: activeTab === item.key ? '2px solid #6b7c3f' : '2px solid transparent',
                cursor: 'pointer',
                transition: 'all 0.2s',
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div style={{ maxWidth: 1200, margin: '0 auto', padding: '16px 24px 24px' }} data-testid="settings-content">
        <Suspense fallback={<SettingsContentFallback />}>
          {activeItem.content}
        </Suspense>
      </div>
    </div>
  )
}

export default Settings
