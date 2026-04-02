import React from 'react'
import {
  Table,
  Button,
  Space,
  Tag,
  Popconfirm,
  message,
  Alert,
  Empty,
  Input,
  Tooltip,
} from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  SyncOutlined,
  UploadOutlined,
  RadarChartOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { sourcesApi } from '../../services/sources'
import { sourceKeys } from '../../services/queryKeys'
import { isXCookieProfile, getDefaultSharedXAuthConfigId } from '../../utils/sourceAuth'
import type { Source, SourceType } from '../../types'
import { formatLocalDateTime } from '../../utils/datetime'
import FetchStatusIcon from './FetchStatusIcon'
import SectionNote from '../ui/SectionNote'
import SourceEditorModal from './SourceEditorModal'
import SourceImportModal from './SourceImportModal'
import { useSourceList, typeFilters } from './hooks/useSourceList'
import { useSourceEditor } from './hooks/useSourceEditor'
import { useSourceImport } from './hooks/useSourceImport'

const typeColors: Record<string, string> = {
  website: 'blue',
  rss: 'gold',
  x: 'cyan',
  youtube: 'red',
}

const strategyLabels: Record<string, string> = {
  rss: 'RSS',
  scrape: '网页抓取',
  js: 'JS渲染',
  rsshub: 'RSSHub',
  nitter: 'Nitter',
  api: '官方API',
  none: '-',
  unknown: '-',
}

const SourceListContainer: React.FC = () => {
  const queryClient = useQueryClient()

  const listState = useSourceList()
  const {
    activeTypeFilter,
    setActiveTypeFilter,
    searchInput,
    setSearchInput,
    debouncedSearch,
    page,
    setPage,
    pageSize,
    setPageSize,
    selectedRowKeys,
    setSelectedRowKeys,
    sources,
    listData,
    isLoading,
    isError,
    isFetching,
    refetchSources,
    categories,
    authConfigs,
    sourceCount,
    maxSources,
    remainingSources,
    sourceLimitReached,
    sourceLoadError,
    getTypeCount,
  } = listState

  const sharedXAuthConfigs = (authConfigs || []).filter(
    (config) => config.is_shared && isXCookieProfile(config)
  )
  const defaultSharedXAuthConfigId = getDefaultSharedXAuthConfigId(sharedXAuthConfigs)

  const editorState = useSourceEditor({
    authConfigs: authConfigs || [],
    sourceLimitReached,
    maxSources,
    sharedXAuthConfigs,
    defaultSharedXAuthConfigId,
  })
  const {
    isModalOpen,
    setIsModalOpen,
    editingSource,
    setEditingSource,
    form,
    createMutation,
    updateMutation,
    deleteMutation,
    fetchMutation,
    probeMutation,
    probeAllMutation,
    handleSubmit,
    handleEdit,
    handleAdd,
    handleTypeChange,
  } = editorState

  const importState = useSourceImport({ remainingSources })
  const {
    isImportModalOpen,
    setIsImportModalOpen,
    importPreview,
    setImportPreview,
    isImporting,
    fileInputRef,
    handleFileSelect,
    handleBulkImport,
  } = importState

  const handleBulkDelete = async () => {
    if (selectedRowKeys.length === 0) return
    try {
      await Promise.all(selectedRowKeys.map((id) => sourcesApi.delete(id as string)))
      queryClient.invalidateQueries({ queryKey: sourceKeys.all })
      message.success(`成功删除 ${selectedRowKeys.length} 个监控源`)
      setSelectedRowKeys([])
    } catch {
      message.error('批量删除失败')
    }
  }

  const handleBulkFetch = async () => {
    if (selectedRowKeys.length === 0) return
    try {
      await Promise.all(selectedRowKeys.map((id) => sourcesApi.triggerFetch(id as string)))
      message.success(`已触发 ${selectedRowKeys.length} 个监控源的抓取任务`)
    } catch {
      message.error('批量抓取失败')
    }
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 180 },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 100,
      render: (type: string) => <Tag color={typeColors[type] || 'default'}>{type}</Tag>,
    },
    {
      title: '可抓取',
      key: 'fetch_status',
      width: 80,
      align: 'center' as const,
      sorter: (a: Source, b: Source) => {
        const order: Record<string, number> = { ok: 0, warning: 1, error: 2, unknown: 3 }
        return (order[a.fetch_status] ?? 3) - (order[b.fetch_status] ?? 3)
      },
      render: (_: unknown, record: Source) => (
        <FetchStatusIcon
          status={record.fetch_status}
          message={record.fetch_status_message}
          strategy={record.fetch_strategy}
        />
      ),
    },
    {
      title: '策略',
      key: 'fetch_strategy',
      width: 90,
      render: (_: unknown, record: Source) => (
        <span style={{ fontSize: 12, color: '#666' }}>
          {strategyLabels[record.fetch_strategy] || record.fetch_strategy || '-'}
        </span>
      ),
    },
    {
      title: 'URL',
      dataIndex: 'url',
      key: 'url',
      ellipsis: true,
      render: (url: string, record: Source) => (
        <>
          <a href={url} target="_blank" rel="noopener noreferrer">{url}</a>
          {Array.isArray(record.extra_urls) && record.extra_urls.length > 0 ? (
            <span style={{ marginLeft: 8, color: '#999', fontSize: 12 }}>
              + {record.extra_urls.length} 个附加 URL
            </span>
          ) : null}
        </>
      ),
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 70,
      render: (enabled: boolean, record: Source) => (
        <Space size={4}>
          <Tag color={enabled ? 'green' : 'default'}>{enabled ? '启用' : '禁用'}</Tag>
          {record.use_keyword_filter && <Tag color="orange">过滤</Tag>}
        </Space>
      ),
    },
    {
      title: '最后抓取',
      dataIndex: 'last_fetched_at',
      key: 'last_fetched_at',
      width: 160,
      render: (time: string | null) => (time ? formatLocalDateTime(time, 'zh-CN') : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 240,
      render: (_: unknown, record: Source) => (
        <Space>
          <Tooltip title="探测可抓取性">
            <Button
              icon={<RadarChartOutlined />}
              size="small"
              onClick={() => probeMutation.mutate(record.id)}
              loading={probeMutation.isPending && probeMutation.variables === record.id}
            />
          </Tooltip>
          <Button icon={<SyncOutlined />} size="small" onClick={() => fetchMutation.mutate(record.id)}>
            抓取
          </Button>
          <Button icon={<EditOutlined />} size="small" onClick={() => handleEdit(record)}>
            编辑
          </Button>
          <Popconfirm
            title="确定要删除这个监控源吗？"
            onConfirm={() => deleteMutation.mutate(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button icon={<DeleteOutlined />} size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const rowSelection = {
    selectedRowKeys,
    onChange: (keys: React.Key[]) => setSelectedRowKeys(keys),
  }

  return (
    <div data-testid="source-manager">
      <input
        type="file"
        accept=".csv"
        ref={fileInputRef}
        style={{ display: 'none' }}
        onChange={handleFileSelect}
      />

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 12,
          marginBottom: 16,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', gap: 0, flexWrap: 'wrap' }}>
          {typeFilters.map((filter, idx) => (
            <button
              key={filter.key}
              onClick={() => { setActiveTypeFilter(filter.key); setSelectedRowKeys([]) }}
              data-testid={`source-filter-${filter.key}`}
              style={{
                padding: '10px 16px',
                fontSize: 14,
                fontWeight: activeTypeFilter === filter.key ? 600 : 400,
                color: activeTypeFilter === filter.key ? '#6b7c3f' : '#666',
                backgroundColor: activeTypeFilter === filter.key ? '#f5f8ef' : 'transparent',
                border: '1px solid #eee',
                borderRight: idx === typeFilters.length - 1 ? '1px solid #eee' : 'none',
                cursor: 'pointer',
              }}
            >
              {filter.label}
              <span style={{ marginLeft: 6, fontSize: 12, color: '#999' }}>
                ({getTypeCount(filter.key)})
              </span>
            </button>
          ))}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <Tooltip title="检测所有源的可抓取性">
            <Button
              icon={<RadarChartOutlined />}
              onClick={() => probeAllMutation.mutate()}
              loading={probeAllMutation.isPending}
              size="small"
            >
              全部探测
            </Button>
          </Tooltip>
          <Button
            icon={<UploadOutlined />}
            onClick={() => fileInputRef.current?.click()}
            size="small"
            disabled={sourceLimitReached}
          >
            导入 CSV
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleAdd}
            size="small"
            disabled={sourceLimitReached}
            style={{ backgroundColor: '#6b7c3f', borderColor: '#6b7c3f' }}
          >
            添加监控源
          </Button>
          <Input
            allowClear
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="搜索信源名称或 URL"
            prefix={<SearchOutlined style={{ color: '#999' }} />}
            data-testid="source-search-input"
            style={{ width: 240 }}
          />
        </div>
      </div>

      <SectionNote
        tone={sourceLimitReached ? 'caution' : 'neutral'}
        style={{ marginBottom: 12 }}
      >
        {sourceLimitReached
          ? `监控源数量已达上限（${sourceCount}/${maxSources}）。新增和批量导入会被阻止。`
          : `监控源配额：${sourceCount}/${maxSources}，还可新增 ${remainingSources} 个。`}
      </SectionNote>

      {isError && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message="信源库加载失败"
          description={sourceLoadError}
          action={
            <Button size="small" onClick={() => refetchSources()} loading={isFetching}>
              重新加载
            </Button>
          }
        />
      )}

      {selectedRowKeys.length > 0 && (
        <div
          style={{
            marginBottom: 16,
            padding: '8px 12px',
            backgroundColor: '#fafafa',
            border: '1px solid #eee',
            borderRadius: 6,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 8,
          }}
        >
          <span style={{ fontSize: 13, color: '#666' }}>
            已选 <strong style={{ color: '#6b7c3f' }}>{selectedRowKeys.length}</strong> 项
          </span>
          <Space>
            <Button
              icon={<RadarChartOutlined />}
              size="small"
              onClick={async () => {
                await Promise.all(selectedRowKeys.map((id) => sourcesApi.probeSource(id as string)))
                queryClient.invalidateQueries({ queryKey: sourceKeys.all })
                message.success(`已探测 ${selectedRowKeys.length} 个源`)
              }}
            >
              批量探测
            </Button>
            <Button icon={<SyncOutlined />} size="small" onClick={handleBulkFetch}>
              批量抓取
            </Button>
            <Popconfirm
              title={`确定要删除选中的 ${selectedRowKeys.length} 个监控源吗？`}
              onConfirm={handleBulkDelete}
              okText="确定"
              cancelText="取消"
            >
              <Button icon={<DeleteOutlined />} size="small" danger>批量删除</Button>
            </Popconfirm>
          </Space>
        </div>
      )}

      <div data-testid="source-table">
        <Table
          rowSelection={rowSelection}
          columns={columns}
          dataSource={sources}
          loading={isLoading}
          rowKey="id"
          locale={{
            emptyText: (
              <Empty
                description={
                  isError
                    ? '信源数据暂时加载失败'
                    : debouncedSearch || activeTypeFilter !== 'all'
                      ? '没有匹配的信源'
                      : '暂无信源'
                }
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            ),
          }}
          pagination={{
            current: page,
            pageSize,
            total: listData?.total ?? 0,
            onChange: (p, ps) => { setPage(p); setPageSize(ps ?? 20) },
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 个信源`,
          }}
          style={{ backgroundColor: '#fff' }}
        />
      </div>

      <SourceEditorModal
        open={isModalOpen}
        editingSource={editingSource}
        form={form}
        categories={categories}
        sharedXAuthConfigs={sharedXAuthConfigs}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        onTypeChange={handleTypeChange as (type: SourceType) => void}
        onSubmit={handleSubmit}
        onClose={() => {
          setIsModalOpen(false)
          setEditingSource(null)
          form.resetFields()
        }}
      />

      <SourceImportModal
        open={isImportModalOpen}
        importPreview={importPreview}
        isImporting={isImporting}
        remainingSources={remainingSources}
        onImport={handleBulkImport}
        onClose={() => { setIsImportModalOpen(false); setImportPreview([]) }}
      />
    </div>
  )
}

export default SourceListContainer
