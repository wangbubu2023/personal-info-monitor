import React, { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Checkbox,
  Collapse,
  Empty,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  DeleteOutlined,
  EditOutlined,
  LinkOutlined,
  LoginOutlined,
  PlusOutlined,
  SafetyOutlined,
} from '@ant-design/icons'
import {
  browserSessionsApi,
  type BrowserSession,
  type BrowserSessionStatus,
} from '../../services/browserSessions'
import { configsApi, type APIConfig, type AuthConfig } from '../../services/configs'
import { formatLocalDateTime } from '../../utils/datetime'
import { isXCookieProfile } from '../../utils/sourceAuth'
import SettingsSection from './SettingsSection'

const { Text, Paragraph } = Typography
const { Password } = Input

type CredentialPlatform = 'youtube' | 'x_twitter'

const STATUS_COPY: Record<BrowserSessionStatus, { color: string; label: string }> = {
  needs_login: { color: 'orange', label: '待登录' },
  active: { color: 'green', label: '已就绪' },
  expired: { color: 'red', label: '已过期' },
  error: { color: 'red', label: '异常' },
}

// A host that, if the user points a browser session at it, receives a nicer
// label in the sessions table. Pure cosmetics; still just normalize_host
// under the hood on the backend.
const FRIENDLY_HOST_LABEL: Record<string, string> = {
  'x.com': 'X (x.com)',
  'twitter.com': 'X (twitter.com)',
  'nytimes.com': '纽约时报 (nytimes.com)',
  'www.nytimes.com': '纽约时报 (nytimes.com)',
  'wsj.com': '华尔街日报 (wsj.com)',
  'www.wsj.com': '华尔街日报 (wsj.com)',
}

interface CreateSessionFormValues {
  site_url: string
}

interface OpenLoginFormValues {
  dwell_seconds: number
  bootstrap_auth_cookies: boolean
}

const CredentialsTab: React.FC = () => {
  const queryClient = useQueryClient()

  // ---- data ---------------------------------------------------------------
  const { data: sessions, isLoading: isLoadingSessions, refetch: refetchSessions } = useQuery({
    queryKey: ['browser-sessions'],
    queryFn: browserSessionsApi.list,
  })
  const { data: apiKeys, isLoading: isLoadingApiKeys } = useQuery({
    queryKey: ['api-keys'],
    queryFn: configsApi.listAPIKeys,
  })
  const { data: authConfigs, isLoading: isLoadingAuthConfigs } = useQuery({
    queryKey: ['auth-configs'],
    queryFn: configsApi.listAuthConfigs,
  })

  const youtubeConfigs = useMemo(
    () => (apiKeys || []).filter((c) => c.platform === 'youtube'),
    [apiKeys],
  )
  const xApiConfigs = useMemo(
    () => (apiKeys || []).filter((c) => c.platform === 'x_twitter'),
    [apiKeys],
  )
  const sharedXProfiles = useMemo(
    () => (authConfigs || []).filter((c) => c.is_shared && isXCookieProfile(c)),
    [authConfigs],
  )

  // ---- ui state ----------------------------------------------------------
  const [createSessionOpen, setCreateSessionOpen] = useState(false)
  const [createSessionPreset, setCreateSessionPreset] = useState<string>('https://www.nytimes.com')
  const [createSessionForm] = Form.useForm<CreateSessionFormValues>()
  const [openingSession, setOpeningSession] = useState<BrowserSession | null>(null)
  const [openForm] = Form.useForm<OpenLoginFormValues>()

  const [apiKeyModalOpen, setApiKeyModalOpen] = useState(false)
  const [editingApiKey, setEditingApiKey] = useState<APIConfig | null>(null)
  const [pendingPlatform, setPendingPlatform] = useState<CredentialPlatform | null>(null)
  const [apiKeyForm] = Form.useForm()

  const [legacyXModalOpen, setLegacyXModalOpen] = useState(false)
  const [editingLegacyX, setEditingLegacyX] = useState<AuthConfig | null>(null)
  const [legacyXForm] = Form.useForm()

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['browser-sessions'] }),
      queryClient.invalidateQueries({ queryKey: ['api-keys'] }),
      queryClient.invalidateQueries({ queryKey: ['auth-configs'] }),
    ])
  }

  // ---- mutations: browser sessions ---------------------------------------
  const createSessionMutation = useMutation({
    mutationFn: browserSessionsApi.create,
    onSuccess: async (created) => {
      await invalidate()
      message.success('已创建登录会话')
      setCreateSessionOpen(false)
      createSessionForm.resetFields()
      setOpeningSession(created)
      openForm.resetFields()
    },
    onError: (err: unknown) => {
      const detail =
        typeof err === 'object' && err && 'response' in err
          ? ((err as any).response?.data?.detail as string | undefined)
          : undefined
      message.error(detail || '创建失败')
    },
  })

  const openLoginMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: OpenLoginFormValues }) =>
      browserSessionsApi.openLogin(id, {
        headless: false,
        bootstrap_auth_cookies: payload.bootstrap_auth_cookies,
        dwell_seconds: payload.dwell_seconds,
      }),
    onSuccess: async (res) => {
      await invalidate()
      const cookies = res.bootstrap?.cookie_count ?? 0
      message.success(`登录窗口已关闭，抓取到 ${cookies} 个 cookie`)
      setOpeningSession(null)
    },
    onError: (err: unknown) => {
      const detail =
        typeof err === 'object' && err && 'response' in err
          ? ((err as any).response?.data?.detail as string | undefined)
          : undefined
      message.error(detail || '登录窗口打开失败，请查看后端日志')
    },
  })

  const validateSessionMutation = useMutation({
    mutationFn: (id: string) => browserSessionsApi.validate(id, {}),
    onSuccess: async (res) => {
      await invalidate()
      if (res.status === 'active') {
        message.success(`会话可用：抓到 ${res.validation?.paragraph_count ?? 0} 段正文`)
      } else {
        message.warning(res.validation?.message || res.last_error || '会话校验未通过')
      }
    },
    onError: (err: unknown) => {
      const detail =
        typeof err === 'object' && err && 'response' in err
          ? ((err as any).response?.data?.detail as string | undefined)
          : undefined
      message.error(detail || '校验失败')
    },
  })

  const deleteSessionMutation = useMutation({
    mutationFn: (id: string) => browserSessionsApi.remove(id),
    onSuccess: async () => {
      await invalidate()
      message.success('已删除')
    },
    onError: () => message.error('删除失败'),
  })

  const bindSourcesMutation = useMutation({
    mutationFn: (id: string) => browserSessionsApi.bindSources(id),
    onSuccess: async (res) => {
      await invalidate()
      const bound = res.bound_sources ?? 0
      if (bound === 0) {
        message.info('没有找到匹配的监控源（未改动）')
      } else {
        message.success(`已绑定 ${bound} 个监控源到该登录态`)
      }
    },
    onError: (err: unknown) => {
      const detail =
        typeof err === 'object' && err && 'response' in err
          ? ((err as any).response?.data?.detail as string | undefined)
          : undefined
      message.error(detail || '绑定失败')
    },
  })

  // ---- mutations: API keys ------------------------------------------------
  const createApiKeyMutation = useMutation({
    mutationFn: configsApi.createAPIKey,
    onSuccess: async () => {
      await invalidate()
      message.success('已添加')
      setApiKeyModalOpen(false)
      apiKeyForm.resetFields()
      setPendingPlatform(null)
    },
    onError: () => message.error('添加失败'),
  })

  const updateApiKeyMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<APIConfig> }) =>
      configsApi.updateAPIKey(id, data),
    onSuccess: async () => {
      await invalidate()
      message.success('已更新')
      setApiKeyModalOpen(false)
      setEditingApiKey(null)
      apiKeyForm.resetFields()
      setPendingPlatform(null)
    },
    onError: () => message.error('更新失败'),
  })

  const deleteApiKeyMutation = useMutation({
    mutationFn: configsApi.deleteAPIKey,
    onSuccess: async () => {
      await invalidate()
      message.success('已删除')
    },
    onError: () => message.error('删除失败'),
  })

  // ---- mutations: legacy X manual cookies --------------------------------
  const upsertLegacyXMutation = useMutation({
    mutationFn: async (params: {
      id?: string
      payload: Parameters<typeof configsApi.createAuthConfig>[0]
    }) => {
      if (params.id) {
        return configsApi.updateAuthConfig(params.id, params.payload)
      }
      return configsApi.createAuthConfig(params.payload)
    },
    onSuccess: async (result) => {
      await invalidate()
      if ((result.bound_sources || 0) > 0) {
        message.success(`已保存，已绑定 ${result.bound_sources} 个 X 源`)
      } else {
        message.success('已保存')
      }
      setLegacyXModalOpen(false)
      setEditingLegacyX(null)
      legacyXForm.resetFields()
    },
    onError: () => message.error('保存失败'),
  })

  const deleteLegacyXMutation = useMutation({
    mutationFn: configsApi.deleteAuthConfig,
    onSuccess: async (result) => {
      await invalidate()
      const parts: string[] = []
      if (result.sources_unlinked) parts.push(`${result.sources_unlinked} 个监控源已解绑`)
      if (result.browser_sessions_unlinked) {
        parts.push(`${result.browser_sessions_unlinked} 个浏览器会话已解绑`)
      }
      message.success(parts.length ? `已删除（${parts.join('，')}）` : '已删除')
    },
    onError: (error: unknown) => {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail ? `删除失败：${detail}` : '删除失败')
    },
  })

  // ---- renderers ---------------------------------------------------------
  const sessionColumns = [
    {
      title: '站点',
      dataIndex: 'site_host',
      key: 'site_host',
      render: (host: string, record: BrowserSession) => {
        const friendly = FRIENDLY_HOST_LABEL[host]
        return (
          <div className="flex flex-col">
            <Text strong>{friendly || host}</Text>
            <Text type="secondary" className="text-xs">
              {record.site_url}
            </Text>
          </div>
        )
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (status: BrowserSessionStatus, record: BrowserSession) => {
        const copy = STATUS_COPY[status] || { color: 'default', label: status }
        return (
          <Tooltip title={record.last_error || undefined}>
            <Tag color={copy.color}>{copy.label}</Tag>
          </Tooltip>
        )
      },
    },
    {
      title: '上次校验',
      dataIndex: 'last_validated_at',
      key: 'last_validated_at',
      width: 180,
      render: (ts: string | null | undefined, record: BrowserSession) => (
        <div className="flex flex-col">
          <span>{ts ? formatLocalDateTime(ts) : '—'}</span>
          {record.metadata_?.last_validation?.paragraph_count != null ? (
            <Text type="secondary" className="text-xs">
              抓到 {record.metadata_.last_validation.paragraph_count} 段正文
            </Text>
          ) : null}
        </div>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 360,
      render: (_: unknown, record: BrowserSession) => (
        <Space size="small" wrap>
          <Button
            size="small"
            icon={<LoginOutlined />}
            onClick={() => {
              setOpeningSession(record)
              openForm.resetFields()
            }}
          >
            重新登录
          </Button>
          <Button
            size="small"
            icon={<SafetyOutlined />}
            loading={validateSessionMutation.isPending && validateSessionMutation.variables === record.id}
            onClick={() => validateSessionMutation.mutate(record.id)}
          >
            校验
          </Button>
          <Tooltip title="把该站点下所有监测源一键绑定到这份登录态（host 匹配 + X 走 auth_config 共享）">
            <Button
              size="small"
              icon={<LinkOutlined />}
              loading={bindSourcesMutation.isPending && bindSourcesMutation.variables === record.id}
              onClick={() => bindSourcesMutation.mutate(record.id)}
            >
              绑定监测源
            </Button>
          </Tooltip>
          <Popconfirm
            title="删除这个会话？"
            description="仅移除数据库记录，本地 profile 目录保留；可随时重新创建。"
            okText="删除"
            cancelText="取消"
            onConfirm={() => deleteSessionMutation.mutate(record.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const apiKeyColumns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => name || '-',
    },
    {
      title: 'API Key',
      dataIndex: 'masked_key',
      key: 'masked_key',
      render: (key: string) => <code>{key || '****'}</code>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={status === 'active' ? 'green' : 'red'}>
          {status === 'active' ? '有效' : '无效'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_: unknown, record: APIConfig) => (
        <Space>
          <Button
            icon={<EditOutlined />}
            size="small"
            onClick={() => {
              setPendingPlatform(null)
              setEditingApiKey(record)
              apiKeyForm.setFieldsValue({ platform: record.platform, name: record.name })
              setApiKeyModalOpen(true)
            }}
          >
            编辑
          </Button>
          <Popconfirm title="确定删除？" onConfirm={() => deleteApiKeyMutation.mutate(record.id)}>
            <Button icon={<DeleteOutlined />} size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const legacyXColumns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string | undefined, record: AuthConfig) =>
        name || `手动 Cookie ${record.id.slice(0, 8)}`,
    },
    {
      title: '绑定源数',
      dataIndex: 'bound_source_count',
      key: 'bound_source_count',
      width: 100,
      render: (count: number) => count ?? 0,
    },
    {
      title: '最近更新',
      dataIndex: 'updated_at',
      key: 'updated_at',
      render: (value: string) => (value ? formatLocalDateTime(value) : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 180,
      render: (_: unknown, record: AuthConfig) => (
        <Space>
          <Button
            icon={<EditOutlined />}
            size="small"
            onClick={() => {
              setEditingLegacyX(record)
              legacyXForm.setFieldsValue({ name: record.name, bind_all_x_sources: true })
              setLegacyXModalOpen(true)
            }}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定要删除吗？"
            description={
              record.bound_source_count ? `当前仍有 ${record.bound_source_count} 个源正在引用。` : undefined
            }
            onConfirm={() => deleteLegacyXMutation.mutate(record.id)}
          >
            <Button icon={<DeleteOutlined />} size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // ---- handlers -----------------------------------------------------------
  const handleCreateSessionPreset = (siteUrl: string) => {
    setCreateSessionPreset(siteUrl)
    createSessionForm.resetFields()
    createSessionForm.setFieldsValue({ site_url: siteUrl })
    setCreateSessionOpen(true)
  }

  const openApiKeyModal = (platform: CredentialPlatform) => {
    setEditingApiKey(null)
    setPendingPlatform(platform)
    apiKeyForm.resetFields()
    apiKeyForm.setFieldsValue({ platform })
    setApiKeyModalOpen(true)
  }

  const handleSubmitApiKey = (values: {
    platform?: string
    name?: string
    api_key?: string
    api_secret?: string
  }) => {
    const platform = (editingApiKey?.platform ?? values.platform) as CredentialPlatform | undefined
    if (!platform) {
      message.error('缺少平台信息')
      return
    }
    if (editingApiKey) {
      updateApiKeyMutation.mutate({ id: editingApiKey.id, data: { ...values, platform } })
      return
    }
    if (!values.api_key) {
      message.error('请输入 API Key')
      return
    }
    createApiKeyMutation.mutate({
      platform,
      name: values.name,
      api_key: values.api_key,
      api_secret: values.api_secret,
    })
  }

  const handleSubmitLegacyX = (values: {
    name?: string
    auth_token?: string
    ct0?: string
    bind_all_x_sources?: boolean
  }) => {
    const authToken = (values.auth_token || '').trim()
    const ct0 = (values.ct0 || '').trim()
    const hasCookieUpdate = Boolean(authToken || ct0)

    if (hasCookieUpdate && (!authToken || !ct0)) {
      message.error('请同时填写 auth_token 和 ct0')
      return
    }
    if (!editingLegacyX && !hasCookieUpdate) {
      message.error('请填写 auth_token 和 ct0')
      return
    }

    const payload = {
      name: (values.name || '').trim() || undefined,
      site_url: 'https://x.com',
      auth_type: 'cookie',
      is_shared: true,
      cookies: hasCookieUpdate ? { auth_token: authToken, ct0 } : undefined,
      bind_all_x_sources: Boolean(values.bind_all_x_sources),
    }
    upsertLegacyXMutation.mutate({ id: editingLegacyX?.id, payload })
  }

  // Any shared X cookie config that WAS NOT populated via a browser session
  // lives in the legacy section. We currently detect "browser-session
  // originated" via cookie_mode=manual + cookie_updated_at presence + being
  // auto-created for an x.com session; the simplest UX heuristic is to show
  // legacy profiles only when there's no active X browser session, plus
  // always show entries the user manually created in the past (legacy name).
  const hasActiveXSession = (sessions || []).some(
    (s) => s.site_host === 'x.com' || s.site_host === 'twitter.com',
  )
  const legacyEntriesToShow = sharedXProfiles.filter((p) => {
    if (!hasActiveXSession) return true
    // Hide auto-generated "X 浏览器会话" rows since they're already
    // surfaced via the session table. Everything else (user pasted old
    // token/ct0) stays visible for cleanup or fallback.
    return p.name !== 'X 浏览器会话'
  })

  return (
    <div className="flex flex-col gap-5">
      <SettingsSection
        title="站点登录会话"
        description="用于需要网页登录态的站点，如纽约时报、WSJ、X 等。点击「重新登录」会弹出可视化浏览器，完成验证码、2FA 或扫码后关闭窗口即可保存会话。"
        actions={
          <Space>
            <Button size="small" onClick={() => refetchSessions()}>
              刷新
            </Button>
            <Button
              type="primary"
              size="small"
              icon={<PlusOutlined />}
              onClick={() => handleCreateSessionPreset('')}
            >
              新建站点登录
            </Button>
          </Space>
        }
        contentClassName="pt-0"
      >
        <Table<BrowserSession>
          rowKey="id"
          loading={isLoadingSessions}
          dataSource={sessions || []}
          columns={sessionColumns}
          pagination={false}
          size="middle"
          locale={{
            emptyText: (
              <Empty
                description="尚未创建任何登录会话"
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            ),
          }}
        />
      </SettingsSection>

      <SettingsSection
        title="平台 API Key"
        description="官方平台接口凭据。YouTube Data API 主要用于部分探测与元数据场景；X API 为付费 Key，按需配置。日常 YouTube 频道抓取仍以 yt-dlp 为主，可不填。"
      >
        <div className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-xl border border-[rgba(88,100,118,0.1)] bg-[#f8fbfc]">
            <div className="flex items-center justify-between gap-3 border-b border-[rgba(88,100,118,0.1)] px-3 py-2.5">
              <div>
                <Text strong className="text-[13px] text-[#2c3a50]">
                  YouTube API
                </Text>
                <p className="mb-0 mt-0.5 text-[12px] text-[#7a8799]">YouTube Data API 凭据</p>
              </div>
              <Button size="small" icon={<PlusOutlined />} onClick={() => openApiKeyModal('youtube')}>
                添加
              </Button>
            </div>
          <Table
            columns={apiKeyColumns}
            dataSource={youtubeConfigs}
            loading={isLoadingApiKeys}
            rowKey="id"
            pagination={false}
            size="small"
            locale={{
              emptyText: (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未配置 YouTube API" />
              ),
            }}
          />
          </div>

          <div className="rounded-xl border border-[rgba(88,100,118,0.1)] bg-[#f8fbfc]">
            <div className="flex items-center justify-between gap-3 border-b border-[rgba(88,100,118,0.1)] px-3 py-2.5">
              <div>
                <Text strong className="text-[13px] text-[#2c3a50]">
                  X API
                </Text>
                <p className="mb-0 mt-0.5 text-[12px] text-[#7a8799]">X / Twitter 官方 API Key</p>
              </div>
              <Button size="small" icon={<PlusOutlined />} onClick={() => openApiKeyModal('x_twitter')}>
                添加
              </Button>
            </div>
          <Table
            columns={apiKeyColumns}
            dataSource={xApiConfigs}
            loading={isLoadingApiKeys}
            rowKey="id"
            pagination={false}
            size="small"
            locale={{
              emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未配置 X API" />,
            }}
          />
        </div>
        </div>
      </SettingsSection>

      {/* ---- 旧版手动 Cookie ---- */}
      {legacyEntriesToShow.length > 0 ? (
        <SettingsSection
          title="旧版手动 Cookie"
          description="仅保留历史手动粘贴的 X Cookie 记录，建议迁移到站点登录会话。"
        >
          <Collapse
            ghost
            items={[
              {
                key: 'legacy-x',
                label: (
                  <span className="text-[13px] text-[#6b7c8f]">
                    旧版：手动粘贴的 X Cookie（{legacyEntriesToShow.length} 条） ·
                    建议迁移到「为 X 登录」
                  </span>
                ),
                children: (
                  <>
                    <Alert
                      type="info"
                      showIcon
                      className="mb-3"
                      message="这是旧的 X 登录方式"
                      description={
                        <span>
                          以前需要手动从浏览器里复制 <code>auth_token</code> / <code>ct0</code>。现在点上方
                          「为 X 登录」走浏览器会话即可，Cookie 会自动同步、过期也只需重新登一次。这里保留旧记录供你清理或作为备份。
                        </span>
                      }
                    />
                    <Table
                      columns={legacyXColumns}
                      dataSource={legacyEntriesToShow}
                      loading={isLoadingAuthConfigs}
                      rowKey="id"
                      pagination={false}
                      size="small"
                    />
                  </>
                ),
              },
            ]}
          />
        </SettingsSection>
      ) : null}

      {/* ---- Modals ---- */}

      {/* 新建会话 */}
      <Modal
        title="新建站点登录会话"
        open={createSessionOpen}
        onCancel={() => {
          setCreateSessionOpen(false)
          createSessionForm.resetFields()
        }}
        onOk={() => createSessionForm.submit()}
        okText="创建并打开登录窗口"
        confirmLoading={createSessionMutation.isPending}
        destroyOnHidden
      >
        <Form
          form={createSessionForm}
          layout="vertical"
          onFinish={(values) =>
            createSessionMutation.mutate({
              site_url: values.site_url.trim(),
              auto_bind_sources: true,
            })
          }
          initialValues={{ site_url: createSessionPreset }}
        >
          <Form.Item
            name="site_url"
            label="站点 URL"
            tooltip="PIM 会以此 URL 的 host 作为会话标识；已绑定相同 host 的网站源（及 X 源）会自动关联。"
            rules={[
              { required: true, message: '请填写站点 URL' },
              {
                validator: (_, v: string) => {
                  if (!v) return Promise.resolve()
                  try {
                    const u = new URL(v.trim())
                    if (!u.host) throw new Error('no host')
                    return Promise.resolve()
                  } catch {
                    return Promise.reject(new Error('需要合法的 http(s) URL'))
                  }
                },
              },
            ]}
          >
            <Input placeholder="https://www.nytimes.com / https://x.com" />
          </Form.Item>
          <Paragraph type="secondary" className="!mb-0 text-xs">
            每个 host 只会保留一个会话。重复创建同 host 会更新现有记录，不会新增 profile 目录。X（x.com）会话会自动生成共享登录态，所有 X 监测源立即受益。
          </Paragraph>
        </Form>
      </Modal>

      {/* 打开登录窗口 */}
      <Modal
        title={`打开登录窗口 · ${openingSession?.site_host ?? ''}`}
        open={!!openingSession}
        onCancel={() => {
          if (!openLoginMutation.isPending) setOpeningSession(null)
        }}
        onOk={() => openForm.submit()}
        okText={openLoginMutation.isPending ? '等待窗口关闭…' : '打开窗口'}
        okButtonProps={{ loading: openLoginMutation.isPending }}
        cancelButtonProps={{ disabled: openLoginMutation.isPending }}
        maskClosable={false}
        keyboard={!openLoginMutation.isPending}
        destroyOnHidden
      >
        <Alert
          type="info"
          showIcon
          className="mb-4"
          message="使用流程"
          description={
            <ol className="m-0 list-decimal pl-5 text-sm">
              <li>点「打开窗口」后 PIM 会弹出一个可视化浏览器，自动导航到站点</li>
              <li>在窗口里完成登录（验证码 / 2FA / 扫码都可以）</li>
              <li>
                登录完成后 <Text strong>手动关闭该浏览器窗口</Text> —— PIM 立刻把登录态存到本地 profile 并同步 Cookie
              </li>
              <li>需要的话回到这里点「校验」验证能抓到正文；不校验也行，抓取流程会自然用上新会话</li>
            </ol>
          }
        />
        <Form
          form={openForm}
          layout="vertical"
          onFinish={(values) => {
            if (!openingSession) return
            openLoginMutation.mutate({ id: openingSession.id, payload: values })
          }}
          initialValues={{ dwell_seconds: 300, bootstrap_auth_cookies: true }}
        >
          <Form.Item
            name="dwell_seconds"
            label="超时上限（秒）"
            tooltip="最多等这么久。绝大多数情况下你会在此之前就关掉窗口，不用担心到点。"
            rules={[{ required: true, message: '必填' }]}
          >
            <InputNumber min={30} max={900} step={30} className="w-full" />
          </Form.Item>
          {openLoginMutation.isPending ? (
            <Alert
              type="warning"
              showIcon
              message="请到弹出的浏览器窗口完成登录，登录完毕后关闭该窗口即可。"
            />
          ) : null}
        </Form>
      </Modal>

      {/* API Key modal */}
      <Modal
        title={
          editingApiKey
            ? editingApiKey.platform === 'youtube'
              ? '编辑 YouTube API Key'
              : '编辑 X API Key'
            : pendingPlatform === 'youtube'
              ? '添加 YouTube API Key'
              : '添加 X API Key'
        }
        open={apiKeyModalOpen}
        onCancel={() => {
          setApiKeyModalOpen(false)
          setEditingApiKey(null)
          setPendingPlatform(null)
        }}
        footer={null}
      >
        <Form form={apiKeyForm} layout="vertical" onFinish={handleSubmitApiKey}>
          <Form.Item name="platform" hidden rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          {editingApiKey ? (
            <Form.Item label="类型">
              <Input
                readOnly
                value={editingApiKey.platform === 'youtube' ? 'YouTube API' : 'X API'}
              />
            </Form.Item>
          ) : null}
          <Form.Item name="name" label="名称（可选）">
            <Input placeholder={pendingPlatform === 'youtube' ? '例如：主 YouTube Key' : '例如：主 X Key'} />
          </Form.Item>
          <Form.Item
            name="api_key"
            label="API Key"
            rules={editingApiKey ? [] : [{ required: true, message: '请输入 API Key' }]}
          >
            <Password placeholder={editingApiKey ? '留空则不更新' : '输入 API Key'} />
          </Form.Item>
          <Form.Item name="api_secret" label="API Secret（如需要）">
            <Password placeholder="部分平台需要" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit">
              {editingApiKey ? '更新' : '添加'}
            </Button>
          </Form.Item>
        </Form>
      </Modal>

      {/* Legacy X cookie modal */}
      <Modal
        title={editingLegacyX ? '编辑手动 X Cookie' : '添加手动 X Cookie（不推荐）'}
        open={legacyXModalOpen}
        onCancel={() => {
          setLegacyXModalOpen(false)
          setEditingLegacyX(null)
        }}
        footer={null}
      >
        <Form form={legacyXForm} layout="vertical" onFinish={handleSubmitLegacyX}>
          <Alert
            type="warning"
            showIcon
            className="mb-4"
            message="建议走「为 X 登录」浏览器会话"
            description="手动粘贴 auth_token / ct0 只作为旧方式保留；Cookie 过期需要再次手动更新。浏览器会话会自动维护登录态。"
          />
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="例如：主账号" />
          </Form.Item>
          <Form.Item
            name="auth_token"
            label="auth_token"
            rules={editingLegacyX ? [] : [{ required: true, message: '请输入 auth_token' }]}
          >
            <Input.Password
              placeholder={editingLegacyX ? '留空则不更新' : '输入 auth_token'}
              autoComplete="off"
            />
          </Form.Item>
          <Form.Item
            name="ct0"
            label="ct0"
            rules={editingLegacyX ? [] : [{ required: true, message: '请输入 ct0' }]}
          >
            <Input.Password
              placeholder={editingLegacyX ? '留空则不更新' : '输入 ct0'}
              autoComplete="off"
            />
          </Form.Item>
          <Form.Item name="bind_all_x_sources" valuePropName="checked" initialValue={true}>
            <Checkbox>保存后一键绑定所有 X 监测源</Checkbox>
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit">
              {editingLegacyX ? '更新' : '添加'}
            </Button>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default CredentialsTab
