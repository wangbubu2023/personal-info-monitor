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
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { configsApi, type APIConfig } from '../../services/configs'
import SectionNote from '../ui/SectionNote'

const { Option } = Select
const { Password } = Input
const MODEL_PROVIDER_PLATFORMS = [
  'openai',
  'anthropic',
  'google',
  'qwen',
  'volcengine',
  'hunyuan',
  'minimax',
  'zhipu',
  'moonshot',
  'deepseek',
  'openai_compatible',
] as const

const ModelProvidersTab: React.FC = () => {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingConfig, setEditingConfig] = useState<APIConfig | null>(null)
  const [form] = Form.useForm()
  const queryClient = useQueryClient()

  const { data: apiKeys, isLoading } = useQuery({
    queryKey: ['api-keys'],
    queryFn: configsApi.listAPIKeys,
  })

  const modelConfigs = (apiKeys || []).filter((k) =>
    MODEL_PROVIDER_PLATFORMS.includes(k.platform as (typeof MODEL_PROVIDER_PLATFORMS)[number])
  )

  const createMutation = useMutation({
    mutationFn: configsApi.createAPIKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      queryClient.invalidateQueries({ queryKey: ['available-models'] })
      message.success('接入配置已添加')
      setIsModalOpen(false)
      form.resetFields()
    },
    onError: () => message.error('添加失败'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) => configsApi.updateAPIKey(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      queryClient.invalidateQueries({ queryKey: ['available-models'] })
      message.success('接入配置已更新')
      setIsModalOpen(false)
      setEditingConfig(null)
      form.resetFields()
    },
    onError: () => message.error('更新失败'),
  })

  const deleteMutation = useMutation({
    mutationFn: configsApi.deleteAPIKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      queryClient.invalidateQueries({ queryKey: ['available-models'] })
      message.success('接入配置已删除')
    },
    onError: () => message.error('删除失败'),
  })

  const platformLabels: Record<string, string> = {
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    google: 'Google (Gemini)',
    qwen: 'Qwen (通义千问)',
    volcengine: '火山方舟 (Doubao)',
    hunyuan: '腾讯混元',
    minimax: 'MiniMax',
    zhipu: '智谱',
    moonshot: 'Moonshot AI (Kimi)',
    deepseek: 'DeepSeek',
    openai_compatible: '自定义兼容接口',
  }

  const columns = [
    { title: '提供商', dataIndex: 'platform', key: 'platform', render: (p: string) => platformLabels[p] || p },
    { title: '名称', dataIndex: 'name', key: 'name', render: (name: string) => name || '-' },
    { title: 'API Base', dataIndex: 'api_base', key: 'api_base', render: (base: string) => base || '-' },
    { title: 'API Key', dataIndex: 'masked_key', key: 'masked_key', render: (key: string) => <code>{key || '****'}</code> },
    { title: '状态', dataIndex: 'status', key: 'status', render: (status: string) => <Tag color={status === 'active' ? 'green' : 'red'}>{status === 'active' ? '有效' : '无效'}</Tag> },
    {
      title: '操作', key: 'actions',
      render: (_: unknown, record: APIConfig) => (
        <Space>
          <Button
            icon={<EditOutlined />}
            size="small"
            onClick={() => {
              setEditingConfig(record)
              form.setFieldsValue({
                platform: record.platform,
                name: record.name,
                api_base: record.api_base,
              })
              setIsModalOpen(true)
            }}
          >
            编辑
          </Button>
          <Popconfirm title="确定要删除这个模型接入配置吗？" onConfirm={() => deleteMutation.mutate(record.id)}>
            <Button icon={<DeleteOutlined />} size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <SectionNote style={{ marginBottom: 16 }}>
        先在这里配置模型供应商的接口凭证。已内置 OpenAI、Anthropic、Google、Qwen、火山方舟、腾讯混元、MiniMax、智谱、Moonshot、DeepSeek 等厂商；暂未内置或需走代理网关的接口，可用“自定义兼容接口”接入。
      </SectionNote>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingConfig(null); form.resetFields(); setIsModalOpen(true) }} style={{ marginBottom: 16 }}>添加模型接入</Button>
      <Table columns={columns} dataSource={modelConfigs} loading={isLoading} rowKey="id" />
      <Modal title={editingConfig ? '编辑模型接入' : '添加模型接入'} open={isModalOpen} onCancel={() => { setIsModalOpen(false); setEditingConfig(null) }} footer={null}>
        <Form
          form={form}
          layout="vertical"
          onFinish={(values) => {
            const payload = {
              platform: values.platform,
              name: values.name,
              api_key: values.api_key,
              api_secret: values.api_secret,
              additional_config: {
                api_base: values.api_base,
              },
            }
            if (editingConfig) {
              const updatePayload: any = {
                name: payload.name,
                additional_config: payload.additional_config,
              }
              if (values.api_key) updatePayload.api_key = values.api_key
              if (values.api_secret) updatePayload.api_secret = values.api_secret
              updateMutation.mutate({ id: editingConfig.id, data: updatePayload })
              return
            }
            createMutation.mutate(payload)
          }}
        >
          <Form.Item name="platform" label="提供商" rules={[{ required: true }]}>
            <Select placeholder="选择提供商">
              <Option value="openai">OpenAI</Option>
              <Option value="anthropic">Anthropic</Option>
              <Option value="google">Google (Gemini)</Option>
              <Option value="qwen">Qwen (通义千问)</Option>
              <Option value="volcengine">火山方舟 (Doubao)</Option>
              <Option value="hunyuan">腾讯混元</Option>
              <Option value="minimax">MiniMax</Option>
              <Option value="zhipu">智谱</Option>
              <Option value="moonshot">Moonshot AI (Kimi)</Option>
              <Option value="deepseek">DeepSeek</Option>
              <Option value="openai_compatible">自定义兼容接口（小米等）</Option>
            </Select>
          </Form.Item>
          <Form.Item name="name" label="名称 (可选)"><Input placeholder="例如：公司 OpenAI Key" /></Form.Item>
          <Form.Item name="api_base" label="API Base (可选)"><Input placeholder="不填将使用该厂商默认地址；自定义兼容接口建议手动填写" /></Form.Item>
          <Form.Item name="api_key" label="API Key" rules={editingConfig ? [] : [{ required: true }]}><Password placeholder={editingConfig ? '留空则不更新' : '输入 API Key'} /></Form.Item>
          <Form.Item name="api_secret" label="API Secret (如需要)"><Password placeholder="某些平台需要 API Secret" /></Form.Item>
          <Form.Item><Button type="primary" htmlType="submit">{editingConfig ? '更新' : '添加'}</Button></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default ModelProvidersTab
