import React from 'react'
import { Modal, Table, Button, Tag } from 'antd'
import type { ImportPreviewItem } from './importUtils'
import type { SourceType } from '../../types'
import SectionNote from '../ui/SectionNote'

const typeColors: Record<string, string> = {
  website: 'blue',
  rss: 'gold',
  x: 'cyan',
  youtube: 'red',
}

const importColumns = [
  { title: '名称', dataIndex: 'name', key: 'name', width: 200 },
  {
    title: '类型',
    dataIndex: 'type',
    key: 'type',
    width: 100,
    render: (type: SourceType) => <Tag color={typeColors[type] || 'default'}>{type}</Tag>,
  },
  { title: 'URL', dataIndex: 'url', key: 'url', ellipsis: true },
  { title: '简介', dataIndex: 'description', key: 'description', ellipsis: true, width: 200 },
]

interface SourceImportModalProps {
  open: boolean
  importPreview: ImportPreviewItem[]
  isImporting: boolean
  remainingSources: number
  onImport: () => void
  onClose: () => void
}

const SourceImportModal: React.FC<SourceImportModalProps> = ({
  open,
  importPreview,
  isImporting,
  remainingSources,
  onImport,
  onClose,
}) => {
  return (
    <Modal
      title={`导入预览 (${importPreview.length} 条)`}
      open={open}
      onCancel={onClose}
      width={900}
      footer={[
        <Button key="cancel" onClick={onClose} disabled={isImporting}>
          取消
        </Button>,
        <Button
          key="import"
          type="primary"
          loading={isImporting}
          onClick={onImport}
          disabled={importPreview.length === 0 || importPreview.length > remainingSources}
        >
          确认导入 ({importPreview.length} 条)
        </Button>,
      ]}
    >
      {importPreview.length > remainingSources ? (
        <SectionNote tone="caution" style={{ marginBottom: 12 }}>
          {`当前最多还能导入 ${remainingSources} 个信源，请减少本次导入数量。`}
        </SectionNote>
      ) : null}
      {isImporting && (
        <SectionNote style={{ marginBottom: 16 }}>
          {`正在导入 ${importPreview.length} 条信源，请稍候...`}
        </SectionNote>
      )}
      <Table
        columns={importColumns}
        dataSource={importPreview}
        rowKey={(record) => record.url}
        size="small"
        pagination={{ pageSize: 10 }}
        scroll={{ y: 400 }}
      />
      <div style={{ marginTop: 16, color: '#666', fontSize: 13 }}>
        <p style={{ marginBottom: 8 }}>* 系统会根据 URL 自动检测监控源类型：</p>
        <ul style={{ marginLeft: 20 }}>
          <li><Tag color="red">youtube</Tag> - YouTube 链接</li>
          <li><Tag color="cyan">x</Tag> - X (Twitter) 链接</li>
          <li><Tag color="gold">rss</Tag> - RSS/Feed 链接</li>
          <li><Tag color="blue">website</Tag> - 其他网站</li>
        </ul>
      </div>
    </Modal>
  )
}

export default SourceImportModal
