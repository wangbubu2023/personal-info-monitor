import { Checkbox, Input, Modal } from 'antd'

export interface ApiKeyPromptResult {
  apiKey: string | null
  remember: boolean
}

export type BootstrapNoticeReason =
  | 'required'
  | 'origin_not_allowed'
  | 'invalid_or_expired'
  | 'cookie_not_persisted'
  | 'unavailable'

const bootstrapNoticeCopy: Record<BootstrapNoticeReason, { title: string; message: string }> = {
  required: {
    title: '此浏览器尚未绑定',
    message: '请在服务器运行 ./pim bootstrap-url，然后直接打开输出的一次性链接。无需复制或输入 Code。',
  },
  origin_not_allowed: {
    title: '当前网站域名未获授权',
    message: '请把当前公网地址配置为 PIM_PUBLIC_URL，重启 PIM，再生成并打开新的一次性链接。',
  },
  invalid_or_expired: {
    title: '一次性链接已失效',
    message: '链接可能已过期或使用过。请重新运行 ./pim bootstrap-url，并直接打开新链接。',
  },
  cookie_not_persisted: {
    title: '浏览器会话未能保存',
    message: '公网部署请使用 HTTPS，并确认浏览器未阻止本站 Cookie；然后重新生成并打开一次性链接。',
  },
  unavailable: {
    title: '暂时无法连接 PIM',
    message: '请确认 PIM 服务已启动且反向代理可访问，然后刷新页面重试。',
  },
}

export function showBootstrapNotice(reason: BootstrapNoticeReason): void {
  const copy = bootstrapNoticeCopy[reason]
  Modal.warning({
    title: copy.title,
    width: 480,
    content: (
      <p className="mb-0 text-sm leading-6 text-[#586476]">
        {copy.message}
      </p>
    ),
    okText: '知道了',
  })
}

export function promptApiKey(): Promise<ApiKeyPromptResult> {
  return new Promise((resolve) => {
    let currentValue = ''
    let remember = true

    Modal.confirm({
      title: '请输入 PIM API Key',
      icon: null,
      width: 440,
      content: (
        <div className="space-y-3 pt-1">
          <Input.Password
            placeholder="API Key"
            autoFocus
            onChange={(e) => {
              currentValue = e.target.value
            }}
          />
          <Checkbox
            defaultChecked
            onChange={(e) => {
              remember = e.target.checked
            }}
          >
            记住此设备（关闭浏览器后仍有效）
          </Checkbox>
          <p className="mb-0 text-xs text-[#586476]">
            API Key 仅由桌面客户端写入系统钥匙串，不会暴露给 Web 页面。
          </p>
        </div>
      ),
      okText: '确认',
      cancelText: '取消',
      onOk: () => {
        const trimmed = currentValue.trim()
        resolve({ apiKey: trimmed || null, remember })
      },
      onCancel: () => resolve({ apiKey: null, remember: false }),
    })
  })
}
