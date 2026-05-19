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
  Dropdown,
} from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  SyncOutlined,
  UploadOutlined,
  DownloadOutlined,
  DownOutlined,
  RadarChartOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { Database } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { sourcesApi } from '../../services/sources'
import { sourceKeys } from '../../services/queryKeys'
import { isXCookieProfile, getDefaultSharedXAuthConfigId } from '../../utils/sourceAuth'
import type { Source } from '../../types'
import { formatLocalDateTime } from '../../utils/datetime'
import FetchStatusIcon from './FetchStatusIcon'
import CategoryPillTabs from '../common/CategoryPillTabs'
import SourceEditorModal from './SourceEditorModal'
import SourceImportModal from './SourceImportModal'
import { useSourceList, typeFilters } from './hooks/useSourceList'
import { useSourceEditor } from './hooks/useSourceEditor'
import { useSourceImport } from './hooks/useSourceImport'
import { downloadSourceBackup, type SourceBackupFormat } from './exportUtils'

const exportFormatLabel: Record<SourceBackupFormat, string> = {
  csv: 'CSV',
  json: 'JSON',
}

const exportMenuItems = [
  { key: 'csv', label: 'CSV（Excel 可直接打开）' },
  { key: 'json', label: 'JSON（完整备份，可无损恢复）' },
]

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

/** 与分类胶囊、资讯顶栏一致的圆角工具条按钮 */
const sourceToolbarBtnSecondary =
  '!inline-flex !h-auto !items-center !gap-1 !rounded-full !border !border-[rgba(88,100,118,0.1)] !bg-white !px-3.5 !py-2 !text-[12px] !font-medium !leading-none !text-[#5f6f82] !shadow-sm hover:!border-[#49A8C9]/35 hover:!text-[#2c3a50] disabled:!opacity-50'
const sourceToolbarBtnPrimary =
  '!inline-flex !h-auto !items-center !gap-1 !rounded-full !border !border-[#49A8C9]/28 !bg-[#49A8C9] !px-3.5 !py-2 !text-[12px] !font-medium !leading-none !text-white !shadow-sm !shadow-[#49A8C9]/15 hover:!bg-[#3d94b3] disabled:!opacity-50'

const toolbarIconStroke = 1.5

const SourceListContainer: React.FC = () => {
  const queryClient = useQueryClient()
  const [isExportingAll, setIsExportingAll] = React.useState(false)
  const [isExportingSelected, setIsExportingSelected] = React.useState(false)

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
    defaultSharedXAuthConfigId,
  })
  const {
    isModalOpen,
    setIsModalOpen,
    editingSource,
    setEditingSource,
    submitError,
    setSubmitError,
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

  const handleExportAll = async (format: SourceBackupFormat) => {
    if (isExportingAll) return
    setIsExportingAll(true)
    try {
      const all = await sourcesApi.listAll()
      if (all.length === 0) {
        message.warning('没有可导出的监控源')
        return
      }
      const filename = downloadSourceBackup(all, { format })
      message.success(
        `已导出 ${all.length} 个监控源（${exportFormatLabel[format]}）· ${filename}`,
      )
    } catch {
      message.error('导出备份失败')
    } finally {
      setIsExportingAll(false)
    }
  }

  const handleExportSelected = async (format: SourceBackupFormat) => {
    if (selectedRowKeys.length === 0 || isExportingSelected) return
    setIsExportingSelected(true)
    try {
      const idSet = new Set(selectedRowKeys.map((key) => String(key)))
      // 当前选中项一定在本页 `sources` 中（翻页 / 筛选切换时会重置选择）
      const selected = sources.filter((s) => idSet.has(s.id))
      if (selected.length === 0) {
        message.warning('选中项已不存在，请刷新列表后重试')
        return
      }
      const filename = downloadSourceBackup(selected, { selected: true, format })
      message.success(
        `已导出 ${selected.length} 个选中监控源（${exportFormatLabel[format]}）· ${filename}`,
      )
    } catch {
      message.error('导出选中监控源失败')
    } finally {
      setIsExportingSelected(false)
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
      title: '探测',
      key: 'probe_status',
      width: 72,
      align: 'center' as const,
      onHeaderCell: () => ({ style: { whiteSpace: 'nowrap' } }),
      sorter: (a: Source, b: Source) => {
        const order: Record<string, number> = {
          ok: 0,
          warning: 1,
          pending: 2,
          error: 3,
          failed: 3,
          not_probed: 4,
          unknown: 5,
        }
        return (order[a.probe_status] ?? 5) - (order[b.probe_status] ?? 5)
      },
      render: (_: unknown, record: Source) => (
        <FetchStatusIcon
          probeMode
          status={record.probe_status}
          message={record.probe_message}
          strategy={record.probe_strategy}
        />
      ),
    },
    {
      title: '抓取',
      key: 'fetch_status',
      width: 72,
      align: 'center' as const,
      onHeaderCell: () => ({ style: { whiteSpace: 'nowrap' } }),
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
      key: 'probe_strategy',
      width: 90,
      render: (_: unknown, record: Source) => (
        <span style={{ fontSize: 12, color: '#666' }}>
          {strategyLabels[record.probe_strategy] || record.probe_strategy || '-'}
        </span>
      ),
    },
    {
      title: 'URL',
      dataIndex: 'url',
      key: 'url',
      width: 280,
      ellipsis: true,
      render: (url: string, record: Source) => (
        <Tooltip
          title={
            <>
              {url}
              {Array.isArray(record.extra_urls) && record.extra_urls.length > 0
                ? `（另有 ${record.extra_urls.length} 个附加 URL）`
                : ''}
            </>
          }
        >
          <span className="block min-w-0">
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="block truncate text-[13px] text-[#49A8C9] hover:text-[#3d94b3]"
            >
              {url}
            </a>
            {Array.isArray(record.extra_urls) && record.extra_urls.length > 0 ? (
              <span className="text-[12px] text-[#8a96a5]">+{record.extra_urls.length}</span>
            ) : null}
          </span>
        </Tooltip>
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
      width: 292,
      fixed: 'right' as const,
      align: 'center' as const,
      onCell: () => ({ style: { whiteSpace: 'nowrap' } }),
      render: (_: unknown, record: Source) => (
        <div className="inline-flex flex-nowrap items-center justify-center gap-1">
          <Tooltip title="探测可抓取性">
            <Button
              type="text"
              icon={<RadarChartOutlined />}
              size="small"
              className="!text-[#5f6f82] hover:!text-[#49A8C9]"
              onClick={() => probeMutation.mutate(record.id)}
              loading={probeMutation.isPending && probeMutation.variables === record.id}
            />
          </Tooltip>
          <Button type="link" size="small" className="!px-1" icon={<SyncOutlined />} onClick={() => fetchMutation.mutate(record.id)}>
            抓取
          </Button>
          <Button type="link" size="small" className="!px-1" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
            编辑
          </Button>
          <Popconfirm
            title="确定要删除这个监控源吗？"
            onConfirm={() => deleteMutation.mutate(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button type="link" size="small" danger className="!px-1" icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </div>
      ),
    },
  ]

  const rowSelection = {
    selectedRowKeys,
    onChange: (keys: React.Key[]) => setSelectedRowKeys(keys),
  }

  return (
    <div className="min-w-0" data-testid="source-manager">
      <input
        type="file"
        accept=".csv"
        ref={fileInputRef}
        style={{ display: 'none' }}
        onChange={handleFileSelect}
      />

      <div className="mb-5 min-w-0 border-b border-[rgba(88,100,118,0.08)] pb-4 sm:mb-6 sm:pb-5">
        {/* 筛选行：类型分类与搜索（同属「筛选信息」） */}
        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
          <div className="min-w-0 flex-1">
            <CategoryPillTabs
              items={typeFilters.map((f) => ({ key: f.key, label: f.label }))}
              activeKey={activeTypeFilter}
              getCount={getTypeCount}
              onSelect={(key) => {
                setActiveTypeFilter(key)
                setSelectedRowKeys([])
              }}
              borderless
              layoutId="source-manager-tab-pill"
              getTabTestId={(key) => `source-filter-${key}`}
            />
          </div>
          <Input
            allowClear
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="搜索监控源名称或 URL"
            prefix={<SearchOutlined className="text-[#94a3b8]" />}
            data-testid="source-search-input"
            className="w-full min-w-0 !rounded-full !border !border-[rgba(88,100,118,0.1)] !bg-white/95 !px-3 !py-1.5 !text-[13px] !shadow-sm sm:max-w-[min(22rem,100%)] sm:shrink-0"
          />
        </div>

        {/* 第二行：配额（与资讯页统计块同款）+ 操作按钮 */}
        <div className="mt-3.5 flex min-w-0 flex-col gap-3 sm:mt-4 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
          <div
            className={`flex w-fit max-w-full flex-wrap items-center gap-2 rounded-lg border px-2.5 py-1.5 shadow-sm ${
              sourceLimitReached
                ? 'border-amber-200/80 bg-amber-50/95'
                : 'border-[rgba(88,100,118,0.08)] bg-white/90'
            }`}
            title={
              sourceLimitReached
                ? `监控源数量已达上限（${sourceCount}/${maxSources}）。新增和批量导入会被阻止。`
                : `监控源配额 ${sourceCount}/${maxSources}，还可新增 ${remainingSources} 个。`
            }
            data-testid="source-quota-inline"
          >
            <Database
              className={`h-3.5 w-3.5 shrink-0 ${sourceLimitReached ? 'text-amber-700' : 'text-[#3a9eb8]'}`}
              strokeWidth={toolbarIconStroke}
              aria-hidden
            />
            <span className={`text-[12px] ${sourceLimitReached ? 'text-amber-900/90' : 'text-[#5f6f82]'}`}>配额</span>
            <span
              className={`text-[14px] font-semibold tabular-nums ${sourceLimitReached ? 'text-amber-950' : 'text-[#2c3a50]'}`}
            >
              {sourceCount}/{maxSources}
            </span>
            {sourceLimitReached ? (
              <span className="text-[12px] font-medium text-amber-800">已达上限</span>
            ) : (
              <>
                <span className="text-[12px] text-[#94a3b8]">·</span>
                <span className="text-[12px] text-[#5f6f82]">还可 {remainingSources} 个</span>
              </>
            )}
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2 sm:justify-end">
            <Tooltip title="检测所有源的可抓取性">
              <Button
                type="default"
                icon={<RadarChartOutlined className="text-[13px]" />}
                onClick={() => probeAllMutation.mutate()}
                loading={probeAllMutation.isPending}
                className={sourceToolbarBtnSecondary}
              >
                全部探测
              </Button>
            </Tooltip>
            <Button
              type="default"
              icon={<UploadOutlined className="text-[13px]" />}
              onClick={() => fileInputRef.current?.click()}
              disabled={sourceLimitReached}
              className={sourceToolbarBtnSecondary}
            >
              导入 CSV
            </Button>
            <Dropdown
              trigger={['click']}
              disabled={sourceCount === 0 || isExportingAll}
              menu={{
                items: exportMenuItems,
                onClick: ({ key }) => handleExportAll(key as SourceBackupFormat),
              }}
            >
              <Button
                type="default"
                icon={<DownloadOutlined className="text-[13px]" />}
                loading={isExportingAll}
                disabled={sourceCount === 0}
                className={sourceToolbarBtnSecondary}
                data-testid="source-export-all"
              >
                导出备份 <DownOutlined className="!ml-1 !text-[10px]" />
              </Button>
            </Dropdown>
            <Button
              type="default"
              icon={<PlusOutlined className="text-[13px]" />}
              onClick={handleAdd}
              disabled={sourceLimitReached}
              className={sourceToolbarBtnPrimary}
            >
              添加监控源
            </Button>
          </div>
        </div>
      </div>

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
                try {
                  await Promise.all(selectedRowKeys.map((id) => sourcesApi.probeSource(id as string)))
                  queryClient.invalidateQueries({ queryKey: sourceKeys.all })
                  message.success(`已探测 ${selectedRowKeys.length} 个源`)
                } catch {
                  message.error('批量探测失败')
                }
              }}
            >
              批量探测
            </Button>
            <Button icon={<SyncOutlined />} size="small" onClick={handleBulkFetch}>
              批量抓取
            </Button>
            <Dropdown
              trigger={['click']}
              disabled={isExportingSelected}
              menu={{
                items: exportMenuItems,
                onClick: ({ key }) => handleExportSelected(key as SourceBackupFormat),
              }}
            >
              <Button
                icon={<DownloadOutlined />}
                size="small"
                loading={isExportingSelected}
                data-testid="source-export-selected"
              >
                导出选中 <DownOutlined className="!ml-1 !text-[10px]" />
              </Button>
            </Dropdown>
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

      <div className="min-w-0 overflow-x-auto pb-1" data-testid="source-table">
        <Table
          rowSelection={rowSelection}
          columns={columns}
          dataSource={sources}
          loading={isLoading}
          rowKey="id"
          scroll={{ x: 1348 }}
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
          authConfigs={authConfigs || []}
          sharedXAuthConfigs={sharedXAuthConfigs}
          isSubmitting={createMutation.isPending || updateMutation.isPending}
          submitError={submitError}
          onTypeChange={handleTypeChange}
        onSubmit={handleSubmit}
        onClose={() => {
          setSubmitError(null)
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
