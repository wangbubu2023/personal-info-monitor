import React from 'react'
import { Tooltip } from 'antd'
import {
  CheckCircleFilled,
  WarningFilled,
  CloseCircleFilled,
  QuestionCircleFilled,
} from '@ant-design/icons'

import type { FetchStatus } from '../../types'

interface FetchStatusIconProps {
  status: FetchStatus
  message?: string
  strategy?: string
}

const FetchStatusIcon: React.FC<FetchStatusIconProps> = ({ status, message, strategy }) => {
  const tooltipText = [
    message,
    strategy && strategy !== 'unknown' && strategy !== 'none' ? `策略: ${strategy}` : null,
  ].filter(Boolean).join(' | ') || '未检测'

  switch (status) {
    case 'ok':
      return <Tooltip title={tooltipText}><CheckCircleFilled style={{ color: '#52c41a', fontSize: 16 }} /></Tooltip>
    case 'warning':
      return <Tooltip title={tooltipText}><WarningFilled style={{ color: '#faad14', fontSize: 16 }} /></Tooltip>
    case 'error':
      return <Tooltip title={tooltipText}><CloseCircleFilled style={{ color: '#ff4d4f', fontSize: 16 }} /></Tooltip>
    default:
      return <Tooltip title="未探测"><QuestionCircleFilled style={{ color: '#d9d9d9', fontSize: 16 }} /></Tooltip>
  }
}

export default FetchStatusIcon
