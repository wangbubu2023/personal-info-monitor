import React, { useState, useRef, useEffect } from 'react'
import { useQuery, useQueries, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  Select,
  Switch,
  Space,
  Tag,
  Popconfirm,
  message,
  InputNumber,
  Tooltip,
  Alert,
  Divider,
  Empty,
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
import { sourcesApi, listSources } from '../../services/sources'
import { categoriesApi } from '../../services/categories'
import { configsApi, type AuthConfig } from '../../services/configs'
import { sourceKeys } from '../../services/queryKeys'
import type { Source, SourceCreate, SourceType, Category } from '../../types'
import { formatLocalDateTime } from '../../utils/datetime'
import { PODCAST_SOURCES_ENABLED } from '../../config/features'
import FetchStatusIcon from './FetchStatusIcon'
import { detectSourceType, parseCSV, parseUrlLines, type ImportPreviewItem } from './importUtils'
import SectionNote from '../ui/SectionNote'

const { Option } = Select

const normalizeHost = (value?: string): string => {
  try {
    if (!value) return ''
    const raw = value.includes('://') ? value : `https://${value}`
    return (new URL(raw).hostname || '').toLowerCase().replace(/^www\./, '')
  } catch {
    return ''
  }
}

const resolveSiteUrlForAuth = (value?: string): string => {
  const host = normalizeHost(value)
  return host ? `https://${host}` : (value || '')
}

const isXCookieProfile = (config: AuthConfig): boolean => {
  const host = normalizeHost(config.site_url)
  return config.auth_type === 'cookie' && (host === 'x.com' || host === 'twitter.com')
}

const getAuthConfigDisplayName = (config: AuthConfig): string =>
  config.name?.trim() || `${normalizeHost(config.site_url) || '凭证'} · ${config.id.slice(0, 8)}`

const getDefaultSharedXAuthConfigId = (configs: AuthConfig[] = []): string | undefined =>
  configs[0]?.id

interface SourceFormValues extends Omit<SourceCreate, 'extra_urls'> {
  extra_urls_text?: string
  paywall_enabled?: boolean
  x_cookie_enabled?: boolean
  x_auth_mode?: 'shared' | 'dedicated'
  x_shared_auth_config_id?: string
  x_auth_name?: string
  auth_type?: string
  login_url?: string
  username?: string
  password?: string
  cookies?: string
  x_auth_token?: string
  x_ct0?: string
}

const typeFilters = [
  { key: 'all', label: '全部' },
  { key: 'website', label: '网站/博客' },
  { key: 'rss', label: 'RSS' },
  { key: 'x', label: 'X (Twitter)' },
  { key: 'youtube', label: 'YouTube' },
]

const SourceManager: React.FC = () => {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingSource, setEditingSource] = useState<Source | null>(null)
  const [isImportModalOpen, setIsImportModalOpen] = useState(false)
  const [importPreview, setImportPreview] = useState<ImportPreviewItem[]>([])
  const [isImporting, setIsImporting] = useState(false)
  const [activeTypeFilter, setActiveTypeFilter] = useState('all')
  const [searchInput, setSearchInput] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [form] = Form.useForm()
  const queryClient = useQueryClient()

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(searchInput.trim()), 300)
    return () => window.clearTimeout(t)
  }, [searchInput])

  useEffect(() => {
    setPage(1)
  }, [debouncedSearch, activeTypeFilter])

  useEffect(() => {
    setSelectedRowKeys([])
  }, [page, pageSize, debouncedSearch, activeTypeFilter])

  const listParams = {
    page,
    page_size: pageSize,
    search: debouncedSearch || undefined,
    type: activeTypeFilter === 'all' ? undefined : activeTypeFilter,
    scope: 'library' as const,
  }

  const {
    data: listData,
    isLoading,
    isError,
    error,
    isFetching,
    refetch: refetchSources,
  } = useQuery({
    queryKey: sourceKeys.list(listParams),
    queryFn: () => listSources(listParams),
  })

  const sources = listData?.items ?? []

  const { data: quotaData } = useQuery({
    queryKey: [...sourceKeys.all, 'quota-total'],
    queryFn: () => listSources({ page: 1, page_size: 1 }),
    staleTime: 30_000,
  })

  const { data: allTabCountData } = useQuery({
    queryKey: [...sourceKeys.all, 'tab-total', 'all', debouncedSearch],
    queryFn: () =>
      listSources({
        page: 1,
        page_size: 1,
        search: debouncedSearch || undefined,
      }),
    staleTime: 30_000,
  })

  const typeTabCountQueries = useQueries({
    queries: typeFilters
      .filter((f) => f.key !== 'all')
      .map((f) => ({
        queryKey: [...sourceKeys.all, 'tab-total', f.key, debouncedSearch],
        queryFn: () =>
          listSources({
            page: 1,
            page_size: 1,
            type: f.key,
            search: debouncedSearch || undefined,
          }),
        staleTime: 30_000,
      })),
  })

  const { data: categories } = useQuery({
    queryKey: ['categories', 'flat'],
    queryFn: () => categoriesApi.list(true),
  })

  const { data: authConfigs } = useQuery({
    queryKey: ['auth-configs'],
    queryFn: configsApi.listAuthConfigs,
  })
  const { data: systemSettings } = useQuery({
    queryKey: ['system-settings'],
    queryFn: configsApi.getSettings,
  })

  const sourceCount = quotaData?.total ?? 0
  const maxSources = Number(systemSettings?.limits?.max_sources || 200)
  const remainingSources = Math.max(0, maxSources - sourceCount)
  const sourceLimitReached = sourceCount >= maxSources
  const sourceLoadError =
    (error as { response?: { data?: { detail?: string } }; message?: string } | null)?.response?.data?.detail ||
    (error as { message?: string } | null)?.message ||
    '信源加载失败，请稍后重试。'
  const sharedXAuthConfigs = (authConfigs || []).filter(
    (config) => config.is_shared && isXCookieProfile(config)
  )
  const defaultSharedXAuthConfigId = getDefaultSharedXAuthConfigId(sharedXAuthConfigs)

  const createMutation = useMutation({
    mutationFn: sourcesApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sourceKeys.all })
      message.success('创建成功')
      setIsModalOpen(false)
      form.resetFields()
    },
    onError: (error: any) => {
      const detail = error?.response?.data?.detail
      message.error(detail ? `创建失败：${detail}` : '创建失败')
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<SourceCreate> }) =>
      sourcesApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sourceKeys.all })
      message.success('更新成功')
      setIsModalOpen(false)
      setEditingSource(null)
      form.resetFields()
    },
    onError: (error: any) => {
      const detail = error?.response?.data?.detail
      message.error(detail ? `更新失败：${detail}` : '更新失败')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: sourcesApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sourceKeys.all })
      message.success('删除成功')
    },
    onError: () => {
      message.error('删除失败')
    },
  })

  const fetchMutation = useMutation({
    mutationFn: sourcesApi.triggerFetch,
    onSuccess: () => {
      message.success('已触发抓取任务')
    },
    onError: () => {
      message.error('触发失败')
    },
  })

  const bulkImportMutation = useMutation({
    mutationFn: sourcesApi.bulkImport,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: sourceKeys.all })
      message.success(`成功导入 ${data.length} 个监控源`)
      setIsImportModalOpen(false)
      setImportPreview([])
    },
    onError: () => {
      message.error('导入失败')
    },
  })

  const probeMutation = useMutation({
    mutationFn: sourcesApi.probeSource,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sourceKeys.all })
      message.success('探测完成')
    },
    onError: () => {
      message.error('探测失败')
    },
  })

  const probeAllMutation = useMutation({
    mutationFn: sourcesApi.probeAll,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: sourceKeys.all })
      message.success(`已探测 ${data.total} 个源`)
    },
    onError: () => {
      message.error('批量探测失败')
    },
  })

  // 批量删除
  const handleBulkDelete = async () => {
    if (selectedRowKeys.length === 0) return
    
    try {
      await Promise.all(selectedRowKeys.map(id => sourcesApi.delete(id as string)))
      queryClient.invalidateQueries({ queryKey: sourceKeys.all })
      message.success(`成功删除 ${selectedRowKeys.length} 个监控源`)
      setSelectedRowKeys([])
    } catch {
      message.error('批量删除失败')
    }
  }

  // 批量抓取
  const handleBulkFetch = async () => {
    if (selectedRowKeys.length === 0) return
    
    try {
      await Promise.all(selectedRowKeys.map(id => sourcesApi.triggerFetch(id as string)))
      message.success(`已触发 ${selectedRowKeys.length} 个监控源的抓取任务`)
    } catch {
      message.error('批量抓取失败')
    }
  }

  // Handle file selection for import
  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (e) => {
      const content = e.target?.result as string
      const parsed = parseCSV(content)
      const preview: ImportPreviewItem[] = parsed.map(item => ({
        ...item,
        type: detectSourceType(item.url),
      }))
      setImportPreview(preview)
      setIsImportModalOpen(true)
    }
    reader.readAsText(file, 'UTF-8')
    
    // Reset file input
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  // Handle bulk import
  const handleBulkImport = async () => {
    if (importPreview.length === 0) return
    if (importPreview.length > remainingSources) {
      message.error(`导入失败：还可新增 ${remainingSources} 个信源，本次准备导入 ${importPreview.length} 个。`)
      return
    }
    
    setIsImporting(true)
    
    const sourcesToImport: SourceCreate[] = importPreview.map(item => ({
      name: item.name,
      type: item.type,
      url: item.url,
      metadata: item.description ? { description: item.description } : undefined,
      fetch_interval: 60,
      enabled: true,
      priority: 0,
    }))
    
    try {
      await bulkImportMutation.mutateAsync(sourcesToImport)
    } finally {
      setIsImporting(false)
    }
  }

  const matchAuthConfigByHost = (url: string, configs: AuthConfig[] = []): AuthConfig | undefined => {
    const sourceHost = normalizeHost(url)
    if (!sourceHost) return undefined
    return configs.find((cfg) => {
      const cfgHost = normalizeHost(cfg.site_url)
      return !!cfgHost && (sourceHost === cfgHost || sourceHost.endsWith(`.${cfgHost}`) || cfgHost.endsWith(`.${sourceHost}`))
    })
  }

  const handleSubmit = async (values: SourceFormValues) => {
    const {
      extra_urls_text,
      paywall_enabled,
      x_cookie_enabled,
      x_auth_mode,
      x_shared_auth_config_id,
      x_auth_name,
      auth_type,
      login_url,
      username,
      password,
      cookies,
      x_auth_token,
      x_ct0,
      ...rest
    } = values

    const payload: SourceCreate = {
      ...rest,
      extra_urls: parseUrlLines(extra_urls_text),
    }

    if (!editingSource && sourceLimitReached) {
      message.warning(`监控源已达上限（${maxSources}），请先删除部分信源再添加。`)
      return
    }

    try {
      if (payload.type === 'website') {
        const enablePaywall = Boolean(paywall_enabled)
        if (enablePaywall) {
          const site_url = resolveSiteUrlForAuth(payload.url)
          let targetAuth =
            authConfigs?.find((cfg) => cfg.id === editingSource?.auth_config_id) ||
            matchAuthConfigByHost(payload.url, authConfigs || [])

          const authPayload = {
            site_url,
            auth_type: auth_type || 'password',
            login_url: login_url || undefined,
            username: username || undefined,
            password: password || undefined,
            cookies: cookies || undefined,
          }

          if (targetAuth) {
            await configsApi.updateAuthConfig(targetAuth.id, authPayload)
          } else {
            targetAuth = await configsApi.createAuthConfig(authPayload)
          }
          await queryClient.invalidateQueries({ queryKey: ['auth-configs'] })

          payload.auth_required = true
          payload.auth_config_id = targetAuth.id
        } else {
          payload.auth_required = false
          ;(payload as SourceCreate & { auth_config_id: string | null }).auth_config_id = null
        }
      } else if (payload.type === 'x') {
        const enableXCookie = Boolean(x_cookie_enabled)
        if (enableXCookie) {
          const selectedMode = x_auth_mode || (sharedXAuthConfigs.length > 0 ? 'shared' : 'dedicated')
          if (selectedMode === 'shared') {
            if (!x_shared_auth_config_id) {
              message.error('保存失败：请选择一个共享 X 登录态')
              return
            }
            payload.auth_required = true
            payload.auth_config_id = x_shared_auth_config_id
          } else {
            const existingLinkedAuth = authConfigs?.find((cfg) => cfg.id === editingSource?.auth_config_id)
            const canReuseExistingDedicated = Boolean(existingLinkedAuth && !existingLinkedAuth.is_shared && isXCookieProfile(existingLinkedAuth))
            const authToken = (x_auth_token || '').trim()
            const ct0 = (x_ct0 || '').trim()
            const profileName = (x_auth_name || '').trim()
            const hasCookieUpdate = Boolean(authToken || ct0)

            if (hasCookieUpdate && (!authToken || !ct0)) {
              message.error('保存失败：请同时填写 auth_token 和 ct0')
              return
            }
            if (!hasCookieUpdate && !canReuseExistingDedicated) {
              message.error('保存失败：请填写专用 X 登录态的 auth_token 和 ct0')
              return
            }

            let savedAuth = existingLinkedAuth
            if (hasCookieUpdate) {
              const authPayload = {
                name: profileName || existingLinkedAuth?.name || `${payload.name} 专用 X 登录态`,
                site_url: 'https://x.com',
                auth_type: 'cookie',
                is_shared: false,
                cookies: { auth_token: authToken, ct0 },
              }
              savedAuth = canReuseExistingDedicated
                ? await configsApi.updateAuthConfig(existingLinkedAuth!.id, authPayload)
                : await configsApi.createAuthConfig(authPayload)
              await queryClient.invalidateQueries({ queryKey: ['auth-configs'] })
            }

            payload.auth_required = true
            payload.auth_config_id = savedAuth?.id
          }
        } else {
          payload.auth_required = false
          ;(payload as SourceCreate & { auth_config_id: string | null }).auth_config_id = null
        }
      }

      if (editingSource) {
        updateMutation.mutate({ id: editingSource.id, data: payload })
      } else {
        createMutation.mutate(payload)
      }
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail ? `保存失败：${detail}` : '保存失败：认证配置未更新')
    }
  }

  const handleEdit = (source: Source) => {
    const linkedAuth =
      authConfigs?.find((cfg) => cfg.id === source.auth_config_id) ||
      (source.type === 'website' ? matchAuthConfigByHost(source.url, authConfigs || []) : undefined)
    setEditingSource(source)
    const xMode = source.type === 'x'
      ? linkedAuth?.is_shared
        ? 'shared'
        : linkedAuth
          ? 'dedicated'
          : sharedXAuthConfigs.length > 0
            ? 'shared'
            : 'dedicated'
      : undefined
    form.setFieldsValue({
      ...source,
      extra_urls_text: (source.extra_urls || []).join('\n'),
      paywall_enabled: Boolean(source.auth_required || source.auth_config_id || linkedAuth),
      x_cookie_enabled: Boolean(source.type === 'x' && (source.auth_required || source.auth_config_id || linkedAuth)),
      x_auth_mode: xMode,
      x_shared_auth_config_id: xMode === 'shared' ? linkedAuth?.id : undefined,
      x_auth_name: !linkedAuth?.is_shared ? linkedAuth?.name || undefined : undefined,
      auth_type: linkedAuth?.auth_type || 'password',
      login_url: linkedAuth?.login_url || undefined,
      username: undefined,
      password: undefined,
      cookies: undefined,
      x_auth_token: undefined,
      x_ct0: undefined,
    })
    setIsModalOpen(true)
  }

  const handleAdd = () => {
    if (sourceLimitReached) {
      message.warning(`监控源已达上限（${maxSources}），请先删除部分信源再添加。`)
      return
    }
    setEditingSource(null)
    form.resetFields()
    form.setFieldsValue({
      paywall_enabled: false,
      x_cookie_enabled: sharedXAuthConfigs.length > 0,
      x_auth_mode: sharedXAuthConfigs.length > 0 ? 'shared' : 'dedicated',
      x_shared_auth_config_id: defaultSharedXAuthConfigId,
      auth_type: 'password',
    })
    setIsModalOpen(true)
  }

  const typeColors: Record<string, string> = {
    website: 'blue',
    rss: 'gold',
    x: 'cyan',
    youtube: 'red',
  }

  const getTypeCount = (typeKey: string): number => {
    if (typeKey === 'all') return allTabCountData?.total ?? 0
    const idx = typeFilters.filter((f) => f.key !== 'all').findIndex((f) => f.key === typeKey)
    if (idx < 0) return 0
    return typeTabCountQueries[idx]?.data?.total ?? 0
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

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 180,
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 100,
      render: (type: string) => (
        <Tag color={typeColors[type] || 'default'}>{type}</Tag>
      ),
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
          <a href={url} target="_blank" rel="noopener noreferrer">
            {url}
          </a>
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
      render: (enabled: boolean) => (
        <Tag color={enabled ? 'green' : 'default'}>
          {enabled ? '启用' : '禁用'}
        </Tag>
      ),
    },
    {
      title: '最后抓取',
      dataIndex: 'last_fetched_at',
      key: 'last_fetched_at',
      width: 160,
      render: (time: string | null) =>
        time ? formatLocalDateTime(time, 'zh-CN') : '-',
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
          <Button
            icon={<SyncOutlined />}
            size="small"
            onClick={() => fetchMutation.mutate(record.id)}
          >
            抓取
          </Button>
          <Button
            icon={<EditOutlined />}
            size="small"
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定要删除这个监控源吗？"
            onConfirm={() => deleteMutation.mutate(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button icon={<DeleteOutlined />} size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // Import preview table columns
  const importColumns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 200,
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 100,
      render: (type: SourceType) => (
        <Tag color={typeColors[type] || 'default'}>{type}</Tag>
      ),
    },
    {
      title: 'URL',
      dataIndex: 'url',
      key: 'url',
      ellipsis: true,
    },
    {
      title: '简介',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      width: 200,
    },
  ]

  // 行选择配置
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
              onClick={() => {
                setActiveTypeFilter(filter.key)
                setSelectedRowKeys([])
              }}
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
            <Button
              icon={<SyncOutlined />}
              size="small"
              onClick={handleBulkFetch}
            >
              批量抓取
            </Button>
            <Popconfirm
              title={`确定要删除选中的 ${selectedRowKeys.length} 个监控源吗？`}
              onConfirm={handleBulkDelete}
              okText="确定"
              cancelText="取消"
            >
              <Button
                icon={<DeleteOutlined />}
                size="small"
                danger
              >
                批量删除
              </Button>
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
                    : (debouncedSearch || activeTypeFilter !== 'all' ? '没有匹配的信源' : '暂无信源')
                }
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            ),
          }}
          pagination={{
            current: page,
            pageSize,
            total: listData?.total ?? 0,
            onChange: (p, ps) => {
              setPage(p)
              setPageSize(ps ?? 20)
            },
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 个信源`,
          }}
          style={{ backgroundColor: '#fff' }}
        />
      </div>

      <Modal
        title={editingSource ? '编辑监控源' : '添加监控源'}
        open={isModalOpen}
        onCancel={() => {
          setIsModalOpen(false)
          setEditingSource(null)
          form.resetFields()
        }}
        footer={null}
        width={600}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input placeholder="例如：TechCrunch" />
          </Form.Item>

          <Form.Item
            name="type"
            label="类型"
            rules={[{ required: true, message: '请选择类型' }]}
          >
            <Select
              placeholder="选择类型"
              onChange={(nextType: SourceType) => {
                if (editingSource) return
                if (nextType === 'x') {
                  form.setFieldsValue({
                    x_cookie_enabled: sharedXAuthConfigs.length > 0,
                    x_auth_mode: sharedXAuthConfigs.length > 0 ? 'shared' : 'dedicated',
                    x_shared_auth_config_id: defaultSharedXAuthConfigId,
                  })
                  return
                }
                form.setFieldsValue({
                  x_cookie_enabled: false,
                  x_auth_mode: sharedXAuthConfigs.length > 0 ? 'shared' : 'dedicated',
                  x_shared_auth_config_id: undefined,
                  x_auth_name: undefined,
                  x_auth_token: undefined,
                  x_ct0: undefined,
                })
              }}
            >
              <Option value="website">网站/博客</Option>
              <Option value="rss">RSS</Option>
              <Option value="x">X (Twitter)</Option>
              <Option value="youtube">YouTube</Option>
              {PODCAST_SOURCES_ENABLED ? <Option value="podcast">播客</Option> : null}
            </Select>
          </Form.Item>

          <Form.Item
            name="url"
            label="URL"
            rules={[
              { required: true, message: '请输入URL' },
              { type: 'url', message: '请输入有效的URL' },
            ]}
          >
            <Input placeholder="https://example.com/feed" />
          </Form.Item>

          <Form.Item
            name="extra_urls_text"
            label="附加 URL（可选）"
            tooltip="每行一个 URL，用于同一信源下抓取多个频道/列表页"
          >
            <Input.TextArea
              placeholder={"https://example.com/channel/a\nhttps://example.com/channel/b"}
              autoSize={{ minRows: 3, maxRows: 6 }}
            />
          </Form.Item>

          <Divider style={{ marginTop: 8, marginBottom: 12 }}>访问凭证</Divider>
          <Form.Item shouldUpdate noStyle>
            {() => {
              const currentType = form.getFieldValue('type')
              if (currentType !== 'website' && currentType !== 'x') return null
              if (currentType === 'x') {
                return (
                  <>
                    <Form.Item
                      name="x_cookie_enabled"
                      label="启用 X 登录态"
                      valuePropName="checked"
                      initialValue={false}
                    >
                      <Switch checkedChildren="启用" unCheckedChildren="关闭" />
                    </Form.Item>

                    <Form.Item shouldUpdate noStyle>
                      {() => {
                        const xCookieEnabled = form.getFieldValue('x_cookie_enabled')
                        if (!xCookieEnabled) return null
                        const xAuthMode = form.getFieldValue('x_auth_mode') || (sharedXAuthConfigs.length > 0 ? 'shared' : 'dedicated')
                        return (
                          <>
                            <SectionNote style={{ marginBottom: 12 }}>
                              平台级 API 凭证仍在“采集凭证”页维护。X 登录态默认建议复用共享配置，只有少数特殊源再单独覆盖。
                            </SectionNote>
                            <Form.Item
                              name="x_auth_mode"
                              label="登录态来源"
                              initialValue={sharedXAuthConfigs.length > 0 ? 'shared' : 'dedicated'}
                            >
                              <Select>
                                <Option value="shared">复用共享 X 登录态</Option>
                                <Option value="dedicated">仅当前源单独配置</Option>
                              </Select>
                            </Form.Item>

                            {xAuthMode === 'shared' ? (
                              <>
                                <Form.Item
                                  name="x_shared_auth_config_id"
                                  label="共享 X 登录态"
                                  rules={[{ required: true, message: '请选择共享 X 登录态' }]}
                                >
                                  <Select
                                    placeholder={
                                      sharedXAuthConfigs.length > 0
                                        ? '选择一个共享 X 登录态'
                                        : '请先到“采集凭证”页添加共享 X 登录态'
                                    }
                                    options={sharedXAuthConfigs.map((config) => ({
                                      value: config.id,
                                      label: `${getAuthConfigDisplayName(config)} (${config.bound_source_count || 0} 个源)`,
                                    }))}
                                  />
                                </Form.Item>
                                {sharedXAuthConfigs.length === 0 ? (
                                  <SectionNote tone="caution" style={{ marginBottom: 12 }}>
                                    当前还没有共享 X 登录态。你可以先去“采集凭证”页添加，或者改为“仅当前源单独配置”。
                                  </SectionNote>
                                ) : null}
                              </>
                            ) : (
                              <>
                                <SectionNote tone="caution" style={{ marginBottom: 12 }}>
                                  专用 X 登录态只绑定到当前监控源，适合少数需要独立账号或独立 Cookie 的例外场景。
                                </SectionNote>
                                <Form.Item
                                  name="x_auth_name"
                                  label="专用登录态名称（可选）"
                                >
                                  <Input placeholder="例如：某个敏感信源专用账号" />
                                </Form.Item>
                                <Form.Item
                                  name="x_auth_token"
                                  label="auth_token"
                                >
                                  <Input.Password placeholder={editingSource ? '留空则不更新' : '输入 auth_token'} autoComplete="off" />
                                </Form.Item>
                                <Form.Item
                                  name="x_ct0"
                                  label="ct0"
                                >
                                  <Input.Password placeholder={editingSource ? '留空则不更新' : '输入 ct0'} autoComplete="off" />
                                </Form.Item>
                              </>
                            )}
                          </>
                        )
                      }}
                    </Form.Item>
                  </>
                )
              }
              return (
                <>
                  <Form.Item
                    name="paywall_enabled"
                    label="启用站点登录态 / 付费墙凭证"
                    valuePropName="checked"
                    initialValue={false}
                  >
                    <Switch checkedChildren="启用" unCheckedChildren="关闭" />
                  </Form.Item>

                  <Form.Item shouldUpdate noStyle>
                    {() => {
                      const paywallEnabled = form.getFieldValue('paywall_enabled')
                      if (!paywallEnabled) return null
                      return (
                        <>
                          <SectionNote style={{ marginBottom: 12 }}>
                            站点凭证只绑定到当前监控源；有 Cookie 时，系统会优先抓取站内直达文章链接，再回退 RSS。
                          </SectionNote>
                          <Form.Item name="auth_type" label="认证方式" initialValue="password">
                            <Select>
                              <Option value="password">用户名密码 + Cookie</Option>
                              <Option value="cookie">Cookie</Option>
                              <Option value="api_key">API Key</Option>
                            </Select>
                          </Form.Item>
                          <Form.Item name="login_url" label="登录页面 URL">
                            <Input placeholder="https://example.com/login" />
                          </Form.Item>
                          <Form.Item name="username" label="用户名">
                            <Input placeholder={editingSource ? '留空则不更新' : ''} />
                          </Form.Item>
                          <Form.Item name="password" label="密码">
                            <Input.Password placeholder={editingSource ? '留空则不更新' : ''} />
                          </Form.Item>
                          <Form.Item
                            name="cookies"
                            label="Cookie（整行粘贴）"
                            tooltip="支持 name1=value1; name2=value2 格式"
                          >
                            <Input.TextArea
                              rows={4}
                              placeholder="例如：wsjregion=na,us; DJSESSIONID=xxx; ..."
                            />
                          </Form.Item>
                        </>
                      )
                    }}
                  </Form.Item>
                </>
              )
            }}
          </Form.Item>

          <Form.Item name="category_id" label="分类">
            <Select placeholder="选择分类" allowClear>
              {categories?.map((cat: Category) => (
                <Option key={cat.id} value={cat.id}>
                  {cat.name}
                </Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item
            name="fetch_interval"
            label="抓取间隔（分钟）"
            initialValue={60}
          >
            <InputNumber min={15} max={1440} style={{ width: '100%' }} />
          </Form.Item>

          <Form.Item
            name="enabled"
            label="启用"
            valuePropName="checked"
            initialValue={true}
          >
            <Switch />
          </Form.Item>

          <Form.Item
            name="priority"
            label="优先级"
            initialValue={0}
          >
            <InputNumber min={0} max={100} style={{ width: '100%' }} />
          </Form.Item>

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={createMutation.isPending || updateMutation.isPending}>
                {editingSource ? '更新' : '创建'}
              </Button>
              <Button onClick={() => setIsModalOpen(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* Import Preview Modal */}
      <Modal
        title={`导入预览 (${importPreview.length} 条)`}
        open={isImportModalOpen}
        onCancel={() => {
          setIsImportModalOpen(false)
          setImportPreview([])
        }}
        width={900}
        footer={[
          <Button 
            key="cancel" 
            onClick={() => {
              setIsImportModalOpen(false)
              setImportPreview([])
            }}
            disabled={isImporting}
          >
            取消
          </Button>,
          <Button
            key="import"
            type="primary"
            loading={isImporting}
            onClick={handleBulkImport}
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
    </div>
  )
}

export default SourceManager
