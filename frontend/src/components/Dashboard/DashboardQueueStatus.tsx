import React from 'react'
import { Tooltip } from 'antd'
import { LoadingOutlined, CheckCircleOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import type { QueueStatus } from '../../services/system'

interface DashboardQueueStatusProps {
  queueStatus?: QueueStatus
  isLoading: boolean
}

const DashboardQueueStatus: React.FC<DashboardQueueStatusProps> = ({ queueStatus, isLoading }) => (
  <div style={{
    borderBottom: '1px solid #eee',
    backgroundColor: '#fafafa',
    padding: '8px 0',
  }} data-testid="dashboard-fetch-status">
    <div style={{
      maxWidth: 1200,
      margin: '0 auto',
      padding: '0 24px',
      display: 'flex',
      alignItems: 'center',
      gap: 24,
      fontSize: 13,
      color: '#666',
    }}>
      <span style={{ fontWeight: 500, color: '#333' }}>抓取状态</span>
      {isLoading ? (
        <span><LoadingOutlined spin /> 加载中…</span>
      ) : queueStatus ? (
        <>
          <Tooltip title="正在并行抓取的源数 / 最大并发数">
            <span>
              抓取中 <strong style={{ color: queueStatus.running_fetches > 0 ? '#6b7c3f' : '#999' }}>{queueStatus.running_fetches}</strong> / {queueStatus.fetch_concurrency}
            </span>
          </Tooltip>
          <span style={{ color: '#ddd' }}>|</span>
          <Tooltip title="正在执行的AI处理任务数">
            <span>
              处理中 <strong style={{ color: queueStatus.running_processes > 0 ? '#6b7c3f' : '#999' }}>{queueStatus.running_processes}</strong>
            </span>
          </Tooltip>
          {queueStatus.sources_status?.some((source) => source.last_error) && (
            <>
              <span style={{ color: '#ddd' }}>|</span>
              <span style={{ color: '#c41d7f' }}>
                <ExclamationCircleOutlined /> {queueStatus.sources_status.filter((source) => source.last_error).length} 个源有错误
              </span>
            </>
          )}
          {queueStatus.sources_status?.length > 0 && !queueStatus.sources_status?.some((source) => source.last_error) && (
            <span style={{ color: '#52c41a', marginLeft: 'auto' }}>
              <CheckCircleOutlined /> 共 {queueStatus.sources_status.length} 个源
            </span>
          )}
        </>
      ) : (
        <span style={{ color: '#999' }}>无法获取系统状态</span>
      )}
    </div>
  </div>
)

export default DashboardQueueStatus
