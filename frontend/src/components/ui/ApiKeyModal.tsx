import { Checkbox, Input, Modal } from 'antd'

export interface ApiKeyPromptResult {
  apiKey: string | null
  remember: boolean
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
            也可运行 <code className="rounded bg-black/5 px-1">./pim bootstrap-url</code> 获取免输入链接。
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
