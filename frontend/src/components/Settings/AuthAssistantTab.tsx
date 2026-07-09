import React, { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Descriptions, Empty, Input, Popconfirm, QRCode, Space, Table, Tag, Typography, message } from 'antd'
import { CopyOutlined, DeleteOutlined, LinkOutlined, ReloadOutlined } from '@ant-design/icons'
import { authAssistantApi, type AuthAssistantDevice, type AuthAssistantPairingToken } from '../../services/authAssistant'
import { getApiBaseURL } from '../../services/api'
import { formatLocalDateTime } from '../../utils/datetime'
import SettingsSection from './SettingsSection'

const { Paragraph, Text } = Typography

function inferPublicServerURL(): string {
  const apiBase = getApiBaseURL()
  if (/^https?:\/\//.test(apiBase)) {
    return apiBase.replace(/\/api\/?$/, '')
  }
  if (typeof window !== 'undefined') {
    return window.location.origin
  }
  return ''
}

const AuthAssistantTab: React.FC = () => {
  const queryClient = useQueryClient()
  const [pairingToken, setPairingToken] = useState<AuthAssistantPairingToken | null>(null)
  const serverURL = useMemo(() => inferPublicServerURL(), [])

  const { data: devices, isLoading, refetch } = useQuery({
    queryKey: ['auth-assistant-devices'],
    queryFn: authAssistantApi.listDevices,
  })

  const createPairingMutation = useMutation({
    mutationFn: () => authAssistantApi.createPairingToken(10),
    onSuccess: (data) => {
      setPairingToken(data)
      message.success('已生成 10 分钟有效的一次性配对码')
    },
    onError: () => message.error('生成配对码失败'),
  })

  const revokeMutation = useMutation({
    mutationFn: authAssistantApi.revokeDevice,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['auth-assistant-devices'] })
      message.success('已移除该设备')
    },
    onError: () => message.error('移除设备失败'),
  })

  const copyText = async (value: string, successText: string) => {
    try {
      await navigator.clipboard.writeText(value)
      message.success(successText)
    } catch {
      message.error('复制失败，请手动选择复制')
    }
  }

  const columns = [
    {
      title: '设备',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: AuthAssistantDevice) => (
        <div className="flex flex-col">
          <Text strong>{name || 'PIM Auth Assistant'}</Text>
          <Text type="secondary" className="text-xs">
            {record.app_version ? `版本 ${record.app_version}` : '未上报版本'}
          </Text>
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (status: string) => <Tag color={status === 'active' ? 'green' : 'default'}>{status === 'active' ? '已连接' : '已移除'}</Tag>,
    },
    {
      title: '最近连接',
      dataIndex: 'last_seen_at',
      key: 'last_seen_at',
      width: 180,
      render: (value: string | null | undefined) => (value ? formatLocalDateTime(value) : '—'),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (value: string | null | undefined) => (value ? formatLocalDateTime(value) : '—'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 120,
      render: (_: unknown, record: AuthAssistantDevice) => (
        <Popconfirm
          title="移除这个 Auth Assistant？"
          description="移除后该本地应用不能再向这台 PIM 上传登录态，需要重新配对。"
          okText="移除"
          cancelText="取消"
          onConfirm={() => revokeMutation.mutate(record.id)}
          disabled={record.status !== 'active'}
        >
          <Button size="small" danger icon={<DeleteOutlined />} disabled={record.status !== 'active'}>
            移除
          </Button>
        </Popconfirm>
      ),
    },
  ]

  return (
    <div className="flex flex-col gap-5">
      <SettingsSection
        title="连接本地 PIM Auth Assistant"
        description="在 VPS 上打开这里生成一次性配对码，然后在本地 Auth Assistant 输入服务器地址和配对码。配对完成后，本地应用只能上传登录态，不能拿到 PIM 管理 API Key。"
        actions={
          <Button
            type="primary"
            icon={<LinkOutlined />}
            loading={createPairingMutation.isPending}
            onClick={() => createPairingMutation.mutate()}
          >
            生成配对码
          </Button>
        }
      >
        <Alert
          type="info"
          showIcon
          className="mb-4"
          message="推荐流程"
          description={
            <ol className="m-0 list-decimal pl-5 text-sm">
              <li>在 VPS 的 PIM Web 打开本页，点击「生成配对码」。</li>
              <li>本地打开 PIM Auth Assistant，填入服务器地址和配对码完成连接。</li>
              <li>在本地为 X、纽约时报、WSJ 等站点登录，选择「上传到 PIM」。</li>
            </ol>
          }
        />

        <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
          <Card size="small" title="远程 PIM 信息" className="border border-[rgba(88,100,118,0.1)]">
            <Descriptions column={1} size="small" labelStyle={{ width: 110 }}>
              <Descriptions.Item label="服务器地址">
                <Space.Compact className="w-full">
                  <Input readOnly value={serverURL} />
                  <Button icon={<CopyOutlined />} onClick={() => copyText(serverURL, '已复制服务器地址')}>
                    复制
                  </Button>
                </Space.Compact>
              </Descriptions.Item>
              <Descriptions.Item label="配对码">
                {pairingToken ? (
                  <Space.Compact className="w-full">
                    <Input readOnly value={pairingToken.pairing_token} className="font-mono" />
                    <Button icon={<CopyOutlined />} onClick={() => copyText(pairingToken.pairing_token, '已复制配对码')}>
                      复制
                    </Button>
                  </Space.Compact>
                ) : (
                  <Text type="secondary">点击「生成配对码」后显示</Text>
                )}
              </Descriptions.Item>
              <Descriptions.Item label="有效期">
                {pairingToken ? formatLocalDateTime(pairingToken.expires_at) : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="深链">
                {pairingToken ? (
                  <Button size="small" onClick={() => copyText(pairingToken.pairing_url, '已复制深链')}>复制 pim-auth:// 链接</Button>
                ) : (
                  '—'
                )}
              </Descriptions.Item>
            </Descriptions>
            <Paragraph type="secondary" className="!mb-0 !mt-3 text-xs">
              配对码只显示一次，过期或使用后自动失效。若你的 PIM 部署在反向代理后，请在 Auth Assistant 中填写外网可访问的 HTTPS 地址。
            </Paragraph>
          </Card>

          <Card size="small" title="扫码/深链连接" className="border border-[rgba(88,100,118,0.1)] text-center">
            {pairingToken ? (
              <QRCode value={pairingToken.pairing_url} size={196} />
            ) : (
              <div className="flex h-[196px] items-center justify-center rounded-lg bg-[#f8fbfc] text-sm text-[#7a8799]">
                生成配对码后显示二维码
              </div>
            )}
          </Card>
        </div>
      </SettingsSection>

      <SettingsSection
        title="已连接设备"
        description="管理已经配对过的本地 Auth Assistant。移除设备会立即吊销它的上传令牌。"
        actions={
          <Button size="small" icon={<ReloadOutlined />} onClick={() => refetch()}>
            刷新
          </Button>
        }
        contentClassName="pt-0"
      >
        <Table<AuthAssistantDevice>
          rowKey="id"
          loading={isLoading}
          dataSource={devices || []}
          columns={columns}
          pagination={false}
          size="middle"
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未连接任何本地 Auth Assistant" /> }}
        />
      </SettingsSection>
    </div>
  )
}

export default AuthAssistantTab
