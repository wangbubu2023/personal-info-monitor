import React from 'react'
import { Tooltip } from 'antd'
import {
  CheckCircleFilled,
  WarningFilled,
  CloseCircleFilled,
  QuestionCircleFilled,
} from '@ant-design/icons'

import type { FetchStatus, ProbeStatus } from '../../types'

interface FetchStatusIconProps {
  status: FetchStatus | ProbeStatus
  message?: string
  strategy?: string
  /** When true, grey icon means "not checked yet" instead of "unknown fetch". */
  probeMode?: boolean
}

const FetchStatusIcon: React.FC<FetchStatusIconProps> = ({
  status,
  message,
  strategy,
  probeMode = false,
}) => {
  const tooltipText = [
    message,
    strategy && strategy !== 'unknown' && strategy !== 'none' ? `策略: ${strategy}` : null,
  ].filter(Boolean).join(' | ') || (probeMode ? '尚未探测' : '尚未抓取')

  switch (status) {
    case 'ok':
      return <Tooltip title={tooltipText}><CheckCircleFilled style={{ color: '#52c41a', fontSize: 16 }} /></Tooltip>
    case 'warning':
      return <Tooltip title={tooltipText}><WarningFilled style={{ color: '#faad14', fontSize: 16 }} /></Tooltip>
    case 'error':
    case 'failed':
      return <Tooltip title={tooltipText}><CloseCircleFilled style={{ color: '#ff4d4f', fontSize: 16 }} /></Tooltip>
    case 'pending':
      return <Tooltip title={tooltipText}><QuestionCircleFilled style={{ color: '#1677ff', fontSize: 16 }} /></Tooltip>
    case 'not_probed':
      return (
        <Tooltip title={tooltipText}>
          <QuestionCircleFilled style={{ color: '#d9d9d9', fontSize: 16 }} />
        </Tooltip>
      )
    default:
      return (
        <Tooltip title={tooltipText}>
          <QuestionCircleFilled style={{ color: '#d9d9d9', fontSize: 16 }} />
        </Tooltip>
      )
  }
}

export default FetchStatusIcon
