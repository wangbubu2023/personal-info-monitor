import React from 'react'
import { Spin } from 'antd'
import type { Dayjs } from 'dayjs'
import type { DigestItem } from '../../types'
import type { CategoryTab } from './dashboardTypes'
import DashboardItemCard from './DashboardItemCard'

interface DashboardDigestListProps {
  isLoading: boolean
  items: DigestItem[]
  selectedDate: Dayjs
  activeTab: string
  categories: CategoryTab[]
  renderTimePair: (publish?: string, fetched?: string) => string
  renderTranslationAction: (item: DigestItem) => React.ReactNode
}

const DashboardDigestList: React.FC<DashboardDigestListProps> = ({
  isLoading,
  items,
  selectedDate,
  activeTab,
  categories,
  renderTimePair,
  renderTranslationAction,
}) => (
  <div style={{
    maxWidth: 1200,
    margin: '0 auto',
    padding: '0 24px',
  }} data-testid="dashboard-content-list">
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
      <div style={{
        textAlign: 'center',
        padding: 64,
        color: '#999',
      }}>
        <div style={{ fontSize: 16 }}>暂无内容</div>
        <div style={{ fontSize: 14, marginTop: 8 }}>
          {selectedDate.format('YYYY年MM月DD日')} 没有
          {activeTab === 'all' ? '任何' : categories.find((category) => category.key === activeTab)?.label}
          更新
        </div>
      </div>
    )}
  </div>
)

export default DashboardDigestList
