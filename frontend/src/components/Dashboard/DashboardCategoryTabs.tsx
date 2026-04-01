import React from 'react'
import type { CategoryTab } from './dashboardTypes'

interface DashboardCategoryTabsProps {
  categories: CategoryTab[]
  activeTab: string
  getCategoryCount: (key: string) => number
  onSelect: (key: string) => void
}

const DashboardCategoryTabs: React.FC<DashboardCategoryTabsProps> = ({
  categories,
  activeTab,
  getCategoryCount,
  onSelect,
}) => (
  <div style={{
    borderBottom: '1px solid #eee',
    backgroundColor: '#fafafa',
  }} data-testid="dashboard-tabs">
    <div style={{
      maxWidth: 1200,
      margin: '0 auto',
      padding: '0 24px',
      display: 'flex',
      gap: 0,
    }}>
      {categories.map((cat) => (
        <button
          key={cat.key}
          onClick={() => onSelect(cat.key)}
          data-testid={`dashboard-tab-${cat.key}`}
          style={{
            padding: '12px 20px',
            fontSize: 14,
            fontWeight: activeTab === cat.key ? 600 : 400,
            color: activeTab === cat.key ? '#6b7c3f' : '#666',
            backgroundColor: activeTab === cat.key ? '#fff' : 'transparent',
            border: 'none',
            borderBottom: activeTab === cat.key ? '2px solid #6b7c3f' : '2px solid transparent',
            cursor: 'pointer',
            transition: 'all 0.2s',
          }}
        >
          {cat.label}
          <span style={{
            marginLeft: 6,
            fontSize: 12,
            color: activeTab === cat.key ? '#6b7c3f' : '#999',
          }}>
            ({getCategoryCount(cat.key)})
          </span>
        </button>
      ))}
    </div>
  </div>
)

export default DashboardCategoryTabs
