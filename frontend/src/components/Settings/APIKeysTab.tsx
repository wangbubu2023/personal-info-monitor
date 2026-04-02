import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Form,
  Input,
  Button,
  Table,
  Tag,
  Space,
  Modal,
  Select,
  Popconfirm,
  message,
  Empty,
  Divider,
  Typography,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { configsApi, type APIConfig, type AuthConfig } from '../../services/configs'
import { formatLocalDateTime } from '../../utils/datetime'
import { isXCookieProfile } from '../../utils/sourceAuth'
import SectionNote from '../ui/SectionNote'

const { Option } = Select
const { Password } = Input
const { Text } = Typography
const SERVICE_CREDENTIAL_PLATFORMS = ['youtube', 'x_twitter'] as const

const APIKeysTab: React.FC = () => {
  const [isCredentialModalOpen, setIsCredentialModalOpen] = useState(false)
  const [isXProfileModalOpen, setIsXProfileModalOpen] = useState(false)
  const [editingConfig, setEditingConfig] = useState<APIConfig | null>(null)
  const [editingXProfile, setEditingXProfile] = useState<AuthConfig | null>(null)
  const [credentialForm] = Form.useForm()
  const [xProfileForm] = Form.useForm()
  const queryClient = useQueryClient()

  const { data: apiKeys, isLoading: isLoadingApiKeys } = useQuery({
    queryKey: ['api-keys'],
    queryFn: configsApi.listAPIKeys,
  })
  const { data: authConfigs, isLoading: isLoadingAuthConfigs } = useQuery({
    queryKey: ['auth-configs'],
    queryFn: configsApi.listAuthConfigs,
  })

  const serviceConfigs = (apiKeys || []).filter((config) =>
    SERVICE_CREDENTIAL_PLATFORMS.includes(config.platform as (typeof SERVICE_CREDENTIAL_PLATFORMS)[number])
  )
  const sharedXProfiles = (authConfigs || []).filter(
    (config) => config.is_shared && isXCookieProfile(config)
  )

  const invalidateAll = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['api-keys'] }),
      queryClient.invalidateQueries({ queryKey: ['auth-configs'] }),
    ])
  }

  const createMutation = useMutation({
    mutationFn: configsApi.createAPIKey,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      message.success('添加成功')
      setIsCredentialModalOpen(false)
      credentialForm.resetFields()
    },
    onError: () => message.error('添加失败'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<APIConfig> }) =>
      configsApi.updateAPIKey(id, data),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      message.success('更新成功')
      setIsCredentialModalOpen(false)
      setEditingConfig(null)
      credentialForm.resetFields()
    },
    onError: () => message.error('更新失败'),
  })

  const deleteMutation = useMutation({
    mutationFn: configsApi.deleteAPIKey,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      message.success('删除成功')
    },
    onError: () => message.error('删除失败'),
  })

  const createXProfileMutation = useMutation({
    mutationFn: configsApi.createAuthConfig,
    onSuccess: async () => {
      await invalidateAll()
      message.success('共享 X 登录态已添加')
      setIsXProfileModalOpen(false)
      setEditingXProfile(null)
      xProfileForm.resetFields()
    },
    onError: () => message.error('添加失败'),
  })

  const updateXProfileMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof configsApi.updateAuthConfig>[1] }) =>
      configsApi.updateAuthConfig(id, data),
    onSuccess: async () => {
      await invalidateAll()
      message.success('共享 X 登录态已更新')
      setIsXProfileModalOpen(false)
      setEditingXProfile(null)
      xProfileForm.resetFields()
    },
    onError: () => message.error('更新失败'),
  })

  const deleteXProfileMutation = useMutation({
    mutationFn: configsApi.deleteAuthConfig,
    onSuccess: async () => {
      await invalidateAll()
      message.success('共享 X 登录态已删除')
    },
    onError: () => message.error('删除失败'),
  })

  const platformLabels: Record<string, string> = {
    youtube: 'YouTube',
    x_twitter: 'X (Twitter)',
  }

  const credentialColumns = [
    {
      title: '采集平台',
      dataIndex: 'platform',
      key: 'platform',
      render: (platform: string) => platformLabels[platform] || platform,
    },
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
      render: (status: string) => (
        <Tag color={status === 'active' ? 'green' : 'red'}>
          {status === 'active' ? '有效' : '无效'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, record: APIConfig) => (
        <Space>
          <Button
            icon={<EditOutlined />}
            size="small"
            onClick={() => {
              setEditingConfig(record)
              credentialForm.setFieldsValue({ platform: record.platform, name: record.name })
              setIsCredentialModalOpen(true)
            }}
          >
            编辑
          </Button>
          <Popconfirm title="确定要删除这个采集平台凭证吗？" onConfirm={() => deleteMutation.mutate(record.id)}>
            <Button icon={<DeleteOutlined />} size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const xProfileColumns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string | undefined, record: AuthConfig) => name || `共享 X 登录态 ${record.id.slice(0, 8)}`,
    },
    {
      title: '绑定源数',
      dataIndex: 'bound_source_count',
      key: 'bound_source_count',
      width: 100,
      render: (count: number) => count ?? 0,
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
      title: '最近更新',
      dataIndex: 'updated_at',
      key: 'updated_at',
      render: (value: string) => (value ? formatLocalDateTime(value) : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, record: AuthConfig) => (
        <Space>
          <Button
            icon={<EditOutlined />}
            size="small"
            onClick={() => {
              setEditingXProfile(record)
              xProfileForm.setFieldsValue({ name: record.name })
              setIsXProfileModalOpen(true)
            }}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定要删除这个共享 X 登录态吗？"
            description={record.bound_source_count ? `当前仍有 ${record.bound_source_count} 个源正在引用。` : undefined}
            onConfirm={() => deleteXProfileMutation.mutate(record.id)}
          >
            <Button icon={<DeleteOutlined />} size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const handleSubmitCredential = (values: { platform: string; name?: string; api_key?: string; api_secret?: string }) => {
    if (editingConfig) {
      updateMutation.mutate({ id: editingConfig.id, data: values })
      return
    }
    if (!values.api_key) {
      message.error('请输入 API Key')
      return
    }
    createMutation.mutate({
      platform: values.platform,
      name: values.name,
      api_key: values.api_key,
      api_secret: values.api_secret,
    })
  }

  const handleSubmitXProfile = (values: { name?: string; auth_token?: string; ct0?: string }) => {
    const authToken = (values.auth_token || '').trim()
    const ct0 = (values.ct0 || '').trim()
    const hasCookieUpdate = Boolean(authToken || ct0)

    if (hasCookieUpdate && (!authToken || !ct0)) {
      message.error('请同时填写 auth_token 和 ct0')
      return
    }
    if (!editingXProfile && !hasCookieUpdate) {
      message.error('请填写 auth_token 和 ct0')
      return
    }

    const payload = {
      name: (values.name || '').trim() || undefined,
      site_url: 'https://x.com',
      auth_type: 'cookie',
      is_shared: true,
      cookies: hasCookieUpdate ? { auth_token: authToken, ct0 } : undefined,
    }

    if (editingXProfile) {
      updateXProfileMutation.mutate({ id: editingXProfile.id, data: payload })
      return
    }
    createXProfileMutation.mutate(payload)
  }

  return (
    <div>
      <SectionNote style={{ marginBottom: 16 }}>
        这里只管理全局可复用的采集凭证：平台级 API Key，以及可被多个 X 监控源复用的共享登录态。
        模型供应商请到“模型管理”；具体网站的付费墙/登录 Cookie 请在对应监控源的编辑面板里配置。
      </SectionNote>

      <Space style={{ marginBottom: 16 }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            setEditingConfig(null)
            credentialForm.resetFields()
            setIsCredentialModalOpen(true)
          }}
        >
          添加采集平台凭证
        </Button>
      </Space>
      <Table
        columns={credentialColumns}
        dataSource={serviceConfigs}
        loading={isLoadingApiKeys}
        rowKey="id"
        pagination={false}
        locale={{
          emptyText: (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无采集平台凭证"
            />
          ),
        }}
      />

      <Divider>共享 X 登录态</Divider>

      <SectionNote style={{ marginBottom: 16 }}>
        给多个 X 监控源复用同一份登录 Cookie 时，在这里维护共享登录态。单独账号、单独 Cookie 的特殊源，可以直接在监控源编辑面板里单独覆盖。
      </SectionNote>
      <Space style={{ marginBottom: 16 }}>
        <Button
          icon={<PlusOutlined />}
          onClick={() => {
            setEditingXProfile(null)
            xProfileForm.resetFields()
            setIsXProfileModalOpen(true)
          }}
        >
          添加共享 X 登录态
        </Button>
      </Space>
      <Table
        columns={xProfileColumns}
        dataSource={sharedXProfiles}
        loading={isLoadingAuthConfigs}
        rowKey="id"
        locale={{
          emptyText: (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无共享 X 登录态"
            />
          ),
        }}
      />

      <Modal
        title={editingConfig ? '编辑采集平台凭证' : '添加采集平台凭证'}
        open={isCredentialModalOpen}
        onCancel={() => {
          setIsCredentialModalOpen(false)
          setEditingConfig(null)
        }}
        footer={null}
      >
        <Form form={credentialForm} layout="vertical" onFinish={handleSubmitCredential}>
          <Form.Item name="platform" label="采集平台" rules={[{ required: true }]}>
            <Select placeholder="选择采集平台">
              <Option value="youtube">YouTube</Option>
              <Option value="x_twitter">X (Twitter)</Option>
            </Select>
          </Form.Item>
          <Form.Item name="name" label="名称 (可选)">
            <Input placeholder="例如：主 YouTube Key" />
          </Form.Item>
          <Form.Item
            name="api_key"
            label="API Key"
            rules={editingConfig ? [] : [{ required: true }]}
          >
            <Password placeholder={editingConfig ? '留空则不更新' : '输入 API Key'} />
          </Form.Item>
          <Form.Item name="api_secret" label="API Secret (如需要)">
            <Password placeholder="某些平台需要 API Secret" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit">
              {editingConfig ? '更新' : '添加'}
            </Button>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={editingXProfile ? '编辑共享 X 登录态' : '添加共享 X 登录态'}
        open={isXProfileModalOpen}
        onCancel={() => {
          setIsXProfileModalOpen(false)
          setEditingXProfile(null)
        }}
        footer={null}
      >
        <Form form={xProfileForm} layout="vertical" onFinish={handleSubmitXProfile}>
          <SectionNote title="如何获取 X 登录 Cookie" style={{ marginBottom: 16 }}>
            <div>
              1. 先在浏览器里正常登录{' '}
              <a href="https://x.com" target="_blank" rel="noreferrer">
                x.com
              </a>
              。
            </div>
            <div>2. 打开开发者工具，进入“Application / Storage”面板。</div>
            <div>3. 在左侧找到 “Cookies”，选择 `https://x.com`。</div>
            <div>4. 在 Cookie 列表里找到并复制 `auth_token` 和 `ct0` 两项的值。</div>
            <div>5. 粘贴到这里保存即可。若后续退出登录、切换账号或 Cookie 过期，需要重新更新。</div>
            <div style={{ marginTop: 8 }}>
              <Text type="secondary">
                提醒：这两项相当于登录态，请不要发给别人，也不要截图外传。
              </Text>
            </div>
          </SectionNote>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input placeholder="例如：主账号 / 备用账号 A" />
          </Form.Item>
          <Form.Item
            name="auth_token"
            label="auth_token"
            rules={editingXProfile ? [] : [{ required: true, message: '请输入 auth_token' }]}
            extra="在 x.com 的 Cookies 列表中复制 auth_token 的 value。"
          >
            <Input.Password
              placeholder={editingXProfile ? '留空则不更新' : '输入 auth_token'}
              autoComplete="off"
            />
          </Form.Item>
          <Form.Item
            name="ct0"
            label="ct0"
            rules={editingXProfile ? [] : [{ required: true, message: '请输入 ct0' }]}
            extra="在 x.com 的 Cookies 列表中复制 ct0 的 value。"
          >
            <Input.Password
              placeholder={editingXProfile ? '留空则不更新' : '输入 ct0'}
              autoComplete="off"
            />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit">
              {editingXProfile ? '更新' : '添加'}
            </Button>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default APIKeysTab
