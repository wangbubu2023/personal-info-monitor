import React from 'react'
import { Spin, Button } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import type { DigestItem } from '../../types'
import DashboardItemCard from './DashboardItemCard'

interface DashboardSearchResultsProps {
  searchQuery: string
  total: number
  items: DigestItem[]
  isLoading: boolean
  onClearSearch: () => void
  renderTimePair: (publish?: string, fetched?: string) => string
  renderTranslationAction: (item: DigestItem) => React.ReactNode
}

const DashboardSearchResults: React.FC<DashboardSearchResultsProps> = ({
  searchQuery,
  total,
  items,
  isLoading,
  onClearSearch,
  renderTimePair,
  renderTranslationAction,
}) => (
  <div style={{ backgroundColor: '#fff', minHeight: '100vh' }} data-testid="dashboard-search-page">
    <div style={{
      backgroundColor: '#f5f5f5',
      borderBottom: '1px solid #eee',
    }}>
      <div style={{
        maxWidth: 1200,
        margin: '0 auto',
        padding: '16px 24px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <h1 style={{ fontSize: 20, fontWeight: 500, color: '#333', margin: 0 }}>
            <SearchOutlined style={{ marginRight: 8 }} />
            搜索结果
          </h1>
          <span style={{ color: '#ccc' }}>|</span>
          <span style={{ fontSize: 13, color: '#999' }}>
            "{searchQuery}" 共 {total} 条
          </span>
        </div>
        <Button
          size="small"
          onClick={onClearSearch}
          style={{ color: '#6b7c3f', borderColor: '#6b7c3f' }}
        >
          清除搜索
        </Button>
      </div>
    </div>
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '0 24px' }}>
      {isLoading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
          <Spin size="large" />
        </div>
      ) : items.length > 0 ? (
        <div>
          {items.map((item) => (
            <DashboardItemCard
              key={item.id}
              item={item}
              timeText={renderTimePair(item.publish_time, item.fetched_at || item.publish_time)}
              translationAction={renderTranslationAction(item)}
            />
          ))}
        </div>
      ) : (
        <div style={{ textAlign: 'center', padding: 64, color: '#999' }}>
          <div style={{ fontSize: 16 }}>未找到匹配的内容</div>
          <div style={{ fontSize: 14, marginTop: 8 }}>尝试使用不同的关键词搜索</div>
        </div>
      )}
    </div>
  </div>
)

export default DashboardSearchResults
