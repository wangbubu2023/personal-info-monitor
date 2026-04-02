import React from 'react'
import {
  Modal,
  Form,
  Input,
  Select,
  Switch,
  Space,
  Button,
  InputNumber,
  Divider,
} from 'antd'
import type { FormInstance } from 'antd'
import type { Source, Category, SourceType } from '../../types'
import type { AuthConfig } from '../../services/configs'
import { PODCAST_SOURCES_ENABLED } from '../../config/features'
import { getAuthConfigDisplayName } from '../../utils/sourceAuth'
import SectionNote from '../ui/SectionNote'
import type { SourceFormValues } from './hooks/useSourceEditor'

const { Option } = Select

interface SourceEditorModalProps {
  open: boolean
  editingSource: Source | null
  form: FormInstance
  categories: Category[] | undefined
  sharedXAuthConfigs: AuthConfig[]
  isSubmitting: boolean
  onTypeChange: (type: SourceType) => void
  onSubmit: (values: SourceFormValues) => void
  onClose: () => void
}

const SourceEditorModal: React.FC<SourceEditorModalProps> = ({
  open,
  editingSource,
  form,
  categories,
  sharedXAuthConfigs,
  isSubmitting,
  onTypeChange,
  onSubmit,
  onClose,
}) => {
  return (
    <Modal
      title={editingSource ? '编辑监控源' : '添加监控源'}
      open={open}
      onCancel={onClose}
      footer={null}
      width={600}
    >
      <Form form={form} layout="vertical" onFinish={onSubmit}>
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
          <Select placeholder="选择类型" onChange={onTypeChange}>
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
                      const xAuthMode =
                        form.getFieldValue('x_auth_mode') ||
                        (sharedXAuthConfigs.length > 0 ? 'shared' : 'dedicated')
                      return (
                        <>
                          <SectionNote style={{ marginBottom: 12 }}>
                            平台级 API 凭证仍在"采集凭证"页维护。X 登录态默认建议复用共享配置，只有少数特殊源再单独覆盖。
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
                                      : '请先到"采集凭证"页添加共享 X 登录态'
                                  }
                                  options={sharedXAuthConfigs.map((config) => ({
                                    value: config.id,
                                    label: `${getAuthConfigDisplayName(config)} (${config.bound_source_count || 0} 个源)`,
                                  }))}
                                />
                              </Form.Item>
                              {sharedXAuthConfigs.length === 0 ? (
                                <SectionNote tone="caution" style={{ marginBottom: 12 }}>
                                  当前还没有共享 X 登录态。你可以先去"采集凭证"页添加，或者改为"仅当前源单独配置"。
                                </SectionNote>
                              ) : null}
                            </>
                          ) : (
                            <>
                              <SectionNote tone="caution" style={{ marginBottom: 12 }}>
                                专用 X 登录态只绑定到当前监控源，适合少数需要独立账号或独立 Cookie 的例外场景。
                              </SectionNote>
                              <Form.Item name="x_auth_name" label="专用登录态名称（可选）">
                                <Input placeholder="例如：某个敏感信源专用账号" />
                              </Form.Item>
                              <Form.Item name="x_auth_token" label="auth_token">
                                <Input.Password
                                  placeholder={editingSource ? '留空则不更新' : '输入 auth_token'}
                                  autoComplete="off"
                                />
                              </Form.Item>
                              <Form.Item name="x_ct0" label="ct0">
                                <Input.Password
                                  placeholder={editingSource ? '留空则不更新' : '输入 ct0'}
                                  autoComplete="off"
                                />
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

        <Form.Item name="fetch_interval" label="抓取间隔（分钟）" initialValue={60}>
          <InputNumber min={15} max={1440} style={{ width: '100%' }} />
        </Form.Item>

        <Divider style={{ marginTop: 8, marginBottom: 12 }}>内容过滤</Divider>
        <Form.Item
          name="use_keyword_filter"
          label="启用关键词过滤"
          valuePropName="checked"
          initialValue={false}
          tooltip="开启后，只有标题或正文匹配至少一个关键词的内容才会被保存。需先在「设置 → 关键词管理」中配置关键词。"
        >
          <Switch checkedChildren="过滤" unCheckedChildren="全量" />
        </Form.Item>
        <Form.Item shouldUpdate noStyle>
          {() => {
            const filterEnabled = form.getFieldValue('use_keyword_filter')
            if (!filterEnabled) return null
            return (
              <SectionNote style={{ marginBottom: 12 }}>
                已启用关键词过滤：仅标题或正文匹配关键词的内容会被抓取保存，未匹配内容将被跳过。请确保已在「设置 → 关键词管理」中添加关键词。
              </SectionNote>
            )
          }}
        </Form.Item>

        <Form.Item name="enabled" label="启用" valuePropName="checked" initialValue={true}>
          <Switch />
        </Form.Item>

        <Form.Item name="priority" label="优先级" initialValue={0}>
          <InputNumber min={0} max={100} style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={isSubmitting}>
              {editingSource ? '更新' : '创建'}
            </Button>
            <Button onClick={onClose}>取消</Button>
          </Space>
        </Form.Item>
      </Form>
    </Modal>
  )
}

export default SourceEditorModal
