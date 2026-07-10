import { useEffect, useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Steps,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd'
import { CloudUploadOutlined, DeleteOutlined, LinkOutlined, UploadOutlined } from '@ant-design/icons'
import { KeyRound, MonitorPlay, ShieldCheck } from 'lucide-react'
import type { ColumnsType } from 'antd/es/table'
import appIconUrl from '../src-tauri/icons/app-icon.svg'
import { importBundle, importZip, pairWithServer } from './api'
import {
  deleteBundle,
  deleteConnection,
  getActiveConnection,
  loadBundles,
  loadConnections,
  saveActiveConnectionId,
  saveBundle,
  saveConnection,
  type SavedBundle,
  type SavedConnection,
} from './storage'
import {
  cancelAuthCapture,
  exportAuthZipBrowser,
  exportAuthZipDesktop,
  finishAuthCapture,
  isDesktopRuntime,
  startAuthCapture,
  type DesktopCaptureStarted,
} from './desktop'

const { Title, Paragraph, Text } = Typography

interface PairFormValues {
  serverUrl: string
  pairingToken: string
  deviceName: string
}

interface CaptureFormValues {
  siteUrl: string
}

function hostFromBundle(bundle: any): string {
  if (typeof bundle?.site_host === 'string' && bundle.site_host.trim()) return bundle.site_host.trim()
  if (typeof bundle?.site_url === 'string') {
    try {
      return new URL(bundle.site_url).host
    } catch {
      return 'unknown-host'
    }
  }
  return 'unknown-host'
}

function downloadJson(filename: string, value: unknown): void {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function newBundleId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function App() {
  const [pairForm] = Form.useForm<PairFormValues>()
  const [captureForm] = Form.useForm<CaptureFormValues>()
  const [connections, setConnections] = useState<SavedConnection[]>(() => loadConnections())
  const [activeConnectionId, setActiveConnectionId] = useState<string | null>(() => getActiveConnection()?.id || null)
  const [bundles, setBundles] = useState<SavedBundle[]>(() => loadBundles())
  const [selectedBundleIds, setSelectedBundleIds] = useState<React.Key[]>([])
  const [manualModalOpen, setManualModalOpen] = useState(false)
  const [captureModalOpen, setCaptureModalOpen] = useState(false)
  const [manualJson, setManualJson] = useState('')
  const [desktopRuntime, setDesktopRuntime] = useState(false)
  const [captureSession, setCaptureSession] = useState<DesktopCaptureStarted | null>(null)

  useEffect(() => {
    isDesktopRuntime().then(setDesktopRuntime)
  }, [])

  const activeConnection = useMemo(
    () => connections.find((item) => item.id === activeConnectionId) || connections[0] || null,
    [activeConnectionId, connections],
  )

  const selectedBundles = useMemo(
    () => bundles.filter((item) => selectedBundleIds.includes(item.id)),
    [bundles, selectedBundleIds],
  )

  const pairMutation = useMutation({
    mutationFn: pairWithServer,
    onSuccess: (conn) => {
      const next = saveConnection({ ...conn, label: conn.serverUrl })
      setConnections(next)
      setActiveConnectionId(next[0]?.id || null)
      message.success('已连接到远程 PIM')
      pairForm.setFieldsValue({ pairingToken: '' })
    },
    onError: (error: any) => {
      message.error(error?.response?.data?.detail || error?.message || '连接失败')
    },
  })

  const startCaptureMutation = useMutation({
    mutationFn: (values: CaptureFormValues) => startAuthCapture(values.siteUrl),
    onSuccess: (session) => {
      setCaptureSession(session)
      message.info(`请在新窗口完成 ${session.site_host} 登录，然后返回这里完成采集`)
    },
    onError: (error: any) => message.error(error?.message || String(error) || '无法打开登录窗口'),
  })

  const finishCaptureMutation = useMutation({
    mutationFn: () => {
      if (!captureSession) throw new Error('尚未开始采集')
      return finishAuthCapture(captureSession.site_url)
    },
    onSuccess: (result) => {
      const item: SavedBundle = {
        id: newBundleId(),
        name: result.name || `${result.site_host} 登录态`,
        siteHost: result.site_host,
        capturedAt: new Date().toISOString(),
        bundle: result.bundle,
      }
      setBundles(saveBundle(item))
      setCaptureSession(null)
      setCaptureModalOpen(false)
      captureForm.resetFields()
      message.success(`已采集并保存 ${item.siteHost} 登录态`)
    },
    onError: (error: any) => message.error(error?.message || String(error) || '采集失败'),
  })

  const closeCaptureModal = async () => {
    if (captureSession) {
      try {
        await cancelAuthCapture()
      } catch {
        // The user may already have closed the login window.
      }
    }
    setCaptureSession(null)
    setCaptureModalOpen(false)
  }

  const uploadBundleMutation = useMutation({
    mutationFn: (bundle: SavedBundle) => {
      if (!activeConnection) throw new Error('尚未选择 PIM')
      return importBundle(activeConnection, bundle.bundle)
    },
    onSuccess: (result) => message.success(`已上传 ${result.site_host}，绑定 ${result.bound_sources} 个源`),
    onError: (error: any) => message.error(error?.response?.data?.detail || error?.message || '上传失败'),
  })

  const uploadZipMutation = useMutation({
    mutationFn: (file: File) => {
      if (!activeConnection) throw new Error('尚未选择 PIM')
      return importZip(activeConnection, file)
    },
    onSuccess: () => message.success('Zip 已上传到 PIM'),
    onError: (error: any) => message.error(error?.response?.data?.detail || error?.message || 'Zip 上传失败'),
  })

  const exportZipMutation = useMutation({
    mutationFn: async () => {
      const targets = selectedBundles.length > 0 ? selectedBundles : bundles
      if (desktopRuntime) return exportAuthZipDesktop(targets)
      return exportAuthZipBrowser(targets)
    },
    onSuccess: (result) => message.success(`已导出 ${result.profile_count} 个登录态：${result.path}`),
    onError: (error: any) => message.error(error?.message || String(error) || '导出失败'),
  })

  const activeStep = useMemo(() => {
    if (!activeConnection) return 0
    if (bundles.length === 0) return 1
    return 2
  }, [activeConnection, bundles.length])

  const handleSaveManualBundle = () => {
    try {
      const parsed = JSON.parse(manualJson)
      if (parsed?.kind !== 'pim.auth_bundle') {
        message.error('这不是 pim.auth_bundle JSON')
        return
      }
      const siteHost = hostFromBundle(parsed)
      const item: SavedBundle = {
        id: newBundleId(),
        name: parsed.name || `${siteHost} 登录态`,
        siteHost,
        capturedAt: new Date().toISOString(),
        bundle: parsed,
      }
      setBundles(saveBundle(item))
      setManualJson('')
      setManualModalOpen(false)
      message.success('已保存到本地列表')
    } catch {
      message.error('JSON 解析失败')
    }
  }

  const handleSelectConnection = (id: string) => {
    saveActiveConnectionId(id)
    setActiveConnectionId(id)
  }

  const handleDeleteConnection = (id: string) => {
    const next = deleteConnection(id)
    setConnections(next)
    setActiveConnectionId(getActiveConnection(next)?.id || null)
  }

  const connectionColumns: ColumnsType<SavedConnection> = [
    {
      title: '远程 PIM',
      dataIndex: 'label',
      key: 'label',
      render: (label, record) => (
        <div className="stack-tight">
          <Text strong>{label || record.serverUrl}</Text>
          <Text type="secondary" className="small-text">{record.serverUrl}</Text>
        </div>
      ),
    },
    {
      title: '设备',
      dataIndex: 'deviceName',
      key: 'deviceName',
      width: 180,
    },
    {
      title: '状态',
      key: 'status',
      width: 110,
      render: (_, record) => <Tag color={record.id === activeConnection?.id ? 'green' : 'blue'}>{record.id === activeConnection?.id ? '当前' : '已保存'}</Tag>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 190,
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => handleSelectConnection(record.id)} disabled={record.id === activeConnection?.id}>
            切换
          </Button>
          <Popconfirm title="移除这个远程 PIM？" onConfirm={() => handleDeleteConnection(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />}>移除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const bundleColumns: ColumnsType<SavedBundle> = [
    {
      title: '站点',
      dataIndex: 'siteHost',
      key: 'siteHost',
      render: (host, record) => (
        <div className="stack-tight">
          <Text strong>{host}</Text>
          <Text type="secondary" className="small-text">{record.name}</Text>
        </div>
      ),
    },
    {
      title: '采集时间',
      dataIndex: 'capturedAt',
      key: 'capturedAt',
      width: 190,
      render: (value) => new Date(value).toLocaleString(),
    },
    {
      title: '状态',
      key: 'status',
      width: 120,
      render: () => <Tag color="blue">本地已保存</Tag>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 320,
      render: (_, record) => (
        <Space wrap>
          <Button
            size="small"
            type="primary"
            icon={<CloudUploadOutlined />}
            disabled={!activeConnection}
            loading={uploadBundleMutation.isPending && uploadBundleMutation.variables?.id === record.id}
            onClick={() => uploadBundleMutation.mutate(record)}
          >
            上传到当前 PIM
          </Button>
          <Button size="small" onClick={() => downloadJson(`${record.siteHost}.pim-auth-bundle.json`, record.bundle)}>
            导出 JSON
          </Button>
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => setBundles(deleteBundle(record.id))}>
            删除
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <main className="app-shell">
      <section className="hero-card">
        <div className="hero-copy">
          <div className="brand-lockup">
            <img className="brand-icon" src={appIconUrl} alt="" />
            <div className="eyebrow"><KeyRound size={16} /> PIM Auth Assistant</div>
          </div>
          <Title level={1}>本地采集网页登录态，安全上传到远程 PIM</Title>
          <Paragraph>
            支持桌面壳、本地浏览器一键采集、auth export zip 导出，以及多个远程 PIM 实例管理。登录态默认保存在本机，只有你点击上传时才发送到选中的 PIM。
          </Paragraph>
        </div>
        <Steps
          size="small"
          current={activeStep}
          items={[{ title: '连接远程 PIM' }, { title: '采集/导入登录态' }, { title: '上传并绑定源' }]}
        />
      </section>

      <div className="grid">
        <Card title="远程 PIM 管理" className="panel">
          <Space direction="vertical" className="full" size="middle">
            {activeConnection ? (
              <Alert
                type="success"
                showIcon
                icon={<ShieldCheck size={18} />}
                message="当前远程 PIM"
                description={
                  <div className="stack-tight">
                    <Text>{activeConnection.serverUrl}</Text>
                    <Text type="secondary">设备：{activeConnection.deviceName} · 配对时间：{new Date(activeConnection.pairedAt).toLocaleString()}</Text>
                  </div>
                }
              />
            ) : (
              <Alert type="warning" showIcon message="尚未连接远程 PIM" description="请先在 PIM Web 设置页生成配对码，然后在下方完成连接。" />
            )}
            <Form form={pairForm} layout="vertical" initialValues={{ deviceName: 'My Mac Auth Assistant' }} onFinish={(values) => pairMutation.mutate(values)}>
              <Form.Item name="serverUrl" label="PIM 服务器地址" rules={[{ required: true, message: '请输入服务器地址' }]}>
                <Input placeholder="https://pim.example.com" />
              </Form.Item>
              <Form.Item name="pairingToken" label="一次性配对码" rules={[{ required: true, message: '请输入配对码' }]}>
                <Input placeholder="ABCD-2345" />
              </Form.Item>
              <Form.Item name="deviceName" label="设备名称">
                <Input />
              </Form.Item>
              <Button type="primary" htmlType="submit" icon={<LinkOutlined />} loading={pairMutation.isPending}>
                新增/连接 PIM
              </Button>
            </Form>
          </Space>
        </Card>

        <Card title="采集、导入与导出" className="panel">
          <Space direction="vertical" className="full" size="middle">
            <Alert
              type={desktopRuntime ? 'success' : 'info'}
              showIcon
              message={desktopRuntime ? '桌面能力可用' : '当前是浏览器预览模式'}
              description={desktopRuntime ? '可以直接打开独立登录窗口采集 Cookie，并导出 zip 到下载目录。' : '浏览器预览模式不能打开桌面登录窗口，但可以粘贴 JSON、上传/导出 zip。'}
            />
            <Space wrap>
              <Button icon={<MonitorPlay size={15} />} type="primary" disabled={!desktopRuntime} onClick={() => setCaptureModalOpen(true)}>
                一键浏览器采集
              </Button>
              <Button icon={<UploadOutlined />} onClick={() => setManualModalOpen(true)}>
                粘贴 auth bundle JSON
              </Button>
              <Upload
                accept=".zip,application/zip"
                showUploadList={false}
                beforeUpload={(file) => {
                  uploadZipMutation.mutate(file)
                  return false
                }}
              >
                <Button disabled={!activeConnection} loading={uploadZipMutation.isPending}>上传 auth export zip 到当前 PIM</Button>
              </Upload>
              <Button loading={exportZipMutation.isPending} onClick={() => exportZipMutation.mutate()}>
                导出选中为 zip
              </Button>
            </Space>
            <Select
              className="full"
              placeholder="选择当前上传目标 PIM"
              value={activeConnection?.id}
              onChange={handleSelectConnection}
              options={connections.map((item) => ({ label: `${item.label} (${item.deviceName})`, value: item.id }))}
              disabled={connections.length === 0}
            />
          </Space>
        </Card>
      </div>

      <Card title="已保存远程 PIM" className="panel list-panel">
        <Table rowKey="id" dataSource={connections} columns={connectionColumns} pagination={false} size="small" />
      </Card>

      <Card title="本地登录态列表" className="panel list-panel">
        <Table
          rowKey="id"
          dataSource={bundles}
          columns={bundleColumns}
          pagination={false}
          rowSelection={{ selectedRowKeys: selectedBundleIds, onChange: setSelectedBundleIds }}
        />
      </Card>

      <Modal
        title="一键浏览器采集登录态"
        open={captureModalOpen}
        onCancel={closeCaptureModal}
        onOk={() => captureSession ? finishCaptureMutation.mutate() : captureForm.submit()}
        okText={captureSession ? '完成登录，采集 Cookie' : '打开安全登录窗口'}
        okButtonProps={{ loading: startCaptureMutation.isPending || finishCaptureMutation.isPending }}
        cancelButtonProps={{ disabled: startCaptureMutation.isPending || finishCaptureMutation.isPending }}
        maskClosable={false}
        destroyOnHidden
      >
        <Alert
          type="info"
          showIcon
          className="mb-4"
          message="采集流程"
          description="输入站点 URL 后会打开独立的安全登录窗口。完成登录后不要关闭窗口，回到这里点击“完成登录，采集 Cookie”。整个流程由 Auth Assistant 自己完成，不依赖本机安装 PIM CLI。"
        />
        {captureSession ? (
          <Alert
            type="success"
            showIcon
            className="mb-4"
            message={`正在采集 ${captureSession.site_host}`}
            description="登录窗口保持打开时，完成账号登录并确认页面已进入登录状态，然后回到此处完成采集。"
          />
        ) : null}
        <Form
          form={captureForm}
          layout="vertical"
          initialValues={{ siteUrl: 'https://x.com' }}
          onFinish={(values) => startCaptureMutation.mutate(values)}
        >
          <Form.Item name="siteUrl" label="站点 URL" rules={[{ required: true, message: '请输入站点 URL' }]}>
            <Input placeholder="https://x.com / https://www.nytimes.com" disabled={Boolean(captureSession)} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="粘贴 pim.auth_bundle JSON" open={manualModalOpen} onCancel={() => setManualModalOpen(false)} onOk={handleSaveManualBundle} okText="保存到本地" width={760}>
        <Input.TextArea
          value={manualJson}
          onChange={(event) => setManualJson(event.target.value)}
          rows={14}
          placeholder="粘贴 *.pim-auth-bundle.json 内容"
          className="mono-area"
        />
      </Modal>
    </main>
  )
}

export default App
