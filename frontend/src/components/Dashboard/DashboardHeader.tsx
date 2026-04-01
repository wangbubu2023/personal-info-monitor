import React from 'react'
import { DatePicker, Button } from 'antd'
import { SyncOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import type { DashboardStats } from '../../types'

interface DashboardHeaderProps {
  stats?: DashboardStats
  selectedDate: Dayjs
  onDateChange: (date: Dayjs) => void
  onFetchAll: () => void
  isFetching: boolean
}

const DashboardHeader: React.FC<DashboardHeaderProps> = ({
  stats,
  selectedDate,
  onDateChange,
  onFetchAll,
  isFetching,
}) => (
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
        <h1 style={{
          fontSize: 20,
          fontWeight: 500,
          color: '#333',
          margin: 0,
        }}>
          <span data-testid="dashboard-title">资讯监控中心</span>
        </h1>
        <span style={{ color: '#ccc' }}>|</span>
        <span style={{ fontSize: 13, color: '#999' }}>追踪您关注的信息源</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <span style={{ fontSize: 13, color: '#666' }}>
          更新 <strong style={{ color: '#6b7c3f' }}>{stats?.today_total || 0}</strong>
          <span style={{ margin: '0 6px', color: '#ddd' }}>|</span>
          未读 <strong style={{ color: '#6b7c3f' }}>{stats?.unread_count || 0}</strong>
        </span>
        <DatePicker
          value={selectedDate}
          onChange={(date) => date && onDateChange(date)}
          allowClear={false}
          size="small"
          style={{ width: 120 }}
        />
        <Button
          icon={<SyncOutlined spin={isFetching} />}
          onClick={onFetchAll}
          loading={isFetching}
          size="small"
          data-testid="dashboard-fetch-all-btn"
          style={{
            backgroundColor: '#6b7c3f',
            borderColor: '#6b7c3f',
            color: '#fff',
          }}
        >
          抓取
        </Button>
      </div>
    </div>
  </div>
)

export default DashboardHeader
