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
  Alert,
} from 'antd'
import type { FormInstance } from 'antd'
import { Link } from 'react-router-dom'
import type { Source, SourceType } from '../../types'
import type { AuthConfig } from '../../services/configs'
import type { BrowserSession } from '../../services/browserSessions'
import { PODCAST_SOURCES_ENABLED } from '../../config/features'
import { SOURCE_TYPE_CATALOG } from '../../config/sourceTypes'
import { getAuthConfigDisplayName, normalizeHost } from '../../utils/sourceAuth'
import { validateSourceUrlInput } from '../../utils/sourceUrl'
import SectionNote from '../ui/SectionNote'
import {
  browserSessionCredentialValue,
  type SourceFormValues,
} from './hooks/useSourceEditor'

const { Option } = Select

interface SourceEditorModalProps {
  open: boolean
  editingSource: Source | null
  form: FormInstance
  authConfigs: AuthConfig[]
  browserSessions: BrowserSession[]
  sharedXAuthConfigs: AuthConfig[]
  isSubmitting: boolean
  submitError?: string | null
  onTypeChange: (type: SourceType) => void
  onSubmit: (values: SourceFormValues) => void
  onClose: () => void
}

const SourceEditorModal: React.FC<SourceEditorModalProps> = ({
  open,
  editingSource,
  form,
  authConfigs,
  browserSessions,
  sharedXAuthConfigs,
  isSubmitting,
  submitError,
  onTypeChange,
  onSubmit,
  onClose,
}) => {
  /**
   * Auth configs suitable for website paywalls: we exclude shared X cookie
   * profiles (those are managed separately for X sources) and the API-key
   * family (not applicable to website auth flow). We also filter by host so
   * the dropdown only shows credentials actually tied to the current
   * source's domain — matches what the backend auto-binds anyway.
   */
  const websiteAuthConfigs = React.useMemo(() => {
    return (authConfigs || []).filter((cfg) => {
      const authType = (cfg.auth_type || '').toLowerCase()
      if (authType === 'api_key') return false
      // Shared X cookie profiles are handled in the X branch above.
      if (cfg.is_shared && (normalizeHost(cfg.site_url) === 'x.com' || normalizeHost(cfg.site_url) === 'twitter.com')) {
        return false
      }
      return true
    })
  }, [authConfigs])
  const activeWebsiteBrowserSessions = React.useMemo(() => {
    return (browserSessions || []).filter((session) => {
      if (session.status !== 'active') return false
      const host = normalizeHost(session.site_host || session.site_url)
      return host !== 'x.com' && host !== 'twitter.com'
    })
  }, [browserSessions])
  return (
    <Modal
      title={editingSource ? '编辑监控源' : '添加监控源'}
      open={open}
      onCancel={onClose}
      footer={null}
      width={600}
    >
      <Form form={form} layout="vertical" onFinish={onSubmit}>
        {submitError ? (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message={submitError}
          />
        ) : null}

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
            {SOURCE_TYPE_CATALOG.filter(
              (info) => info.enabled || (info.key === 'podcast' && PODCAST_SOURCES_ENABLED),
            ).map((info) => (
              <Option key={info.key} value={info.key}>
                {info.label}
              </Option>
            ))}
          </Select>
        </Form.Item>

        <Form.Item
          name="url"
          label="URL"
          rules={[
            { required: true, message: '请输入URL' },
            {
              validator: async (_, value) => {
                const result = validateSourceUrlInput(value)
                if (result !== true) throw new Error(result)
              },
            },
          ]}
        >
          <Input placeholder="example.com/feed 或 https://example.com/feed" />
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

        <Form.Item label="启用抓取">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Form.Item name="enabled" valuePropName="checked" initialValue={true} noStyle>
              <Switch />
            </Form.Item>
            <span className="text-[12px] leading-5 text-[#7d8797]">
              关闭后会保留这个信源，但暂停自动抓取。
            </span>
          </div>
        </Form.Item>

        <Form.Item shouldUpdate noStyle>
          {() => {
            const enabled = form.getFieldValue('enabled')
            if (enabled === false) return null
            return (
              <Form.Item
                name="fetch_interval"
                label="抓取间隔（分钟）"
                initialValue={60}
                tooltip="仅在启用自动抓取时生效。"
              >
                <InputNumber min={15} max={1440} style={{ width: '100%' }} />
              </Form.Item>
            )
          }}
        </Form.Item>

        <Form.Item shouldUpdate noStyle>
          {() => {
            const currentType = form.getFieldValue('type')
            if (currentType === 'rss' || currentType === 'podcast' || currentType === 'youtube') {
              return null
            }
            return (
              <>
                <Divider style={{ marginTop: 8, marginBottom: 12 }}>登录与凭据</Divider>
                {currentType === 'x' ? (
                  <>
                    <Form.Item
                      name="x_cookie_enabled"
                      label="复用 X 登录态"
                      valuePropName="checked"
                      initialValue={true}
                    >
                      <Switch checkedChildren="启用" unCheckedChildren="关闭" />
                    </Form.Item>

                    <Form.Item shouldUpdate noStyle>
                      {() => {
                        const xCookieEnabled = form.getFieldValue('x_cookie_enabled')
                        if (!xCookieEnabled) return null
                        const usesLegacyDedicated = Boolean(form.getFieldValue('x_legacy_dedicated_auth'))
                        const legacyAuthName = form.getFieldValue('x_legacy_auth_name')
                        return (
                          <>
                            <SectionNote style={{ marginBottom: 12 }}>
                              X 登录态建议统一在「登录与凭据 → 为 X 登录」里用浏览器会话创建；
                              登录一次后所有 X 监测源自动复用，无需手填 Cookie。抓取顺序默认是
                              GraphQL/Cookie → RSSHub → Nitter；X 官方 API 属付费/配额 fallback，
                              只有在信源 metadata 显式开启时才会使用。
                            </SectionNote>
                            {usesLegacyDedicated ? (
                              <SectionNote tone="caution" style={{ marginBottom: 12 }}>
                                当前源仍绑定一份旧的专用 X 登录态
                                {legacyAuthName ? `（${legacyAuthName}）` : ''}
                                。若想统一管理，请到「登录与凭据」页为 x.com 创建浏览器会话后，在这里改为复用共享登录态。
                              </SectionNote>
                            ) : null}
                            <Form.Item
                              name="x_shared_auth_config_id"
                              label="共享 X 登录态"
                            >
                              <Select
                                allowClear
                                placeholder={
                                  sharedXAuthConfigs.length > 0
                                    ? '选择一份共享 X 登录态'
                                    : '请先到「登录与凭据」页为 X 登录'
                                }
                                options={sharedXAuthConfigs.map((config) => ({
                                  value: config.id,
                                  label: `${getAuthConfigDisplayName(config)} (${config.bound_source_count || 0} 个源)`,
                                }))}
                              />
                            </Form.Item>
                            {sharedXAuthConfigs.length === 0 ? (
                              <SectionNote tone="caution" style={{ marginBottom: 12 }}>
                                当前还没有可复用的 X 登录态。请到「登录与凭据」页点击「为 X 登录」完成浏览器登录，Cookie 会自动同步过来。
                              </SectionNote>
                            ) : null}
                          </>
                        )
                      }}
                    </Form.Item>
                  </>
                ) : (
                  <>
                    <Form.Item
                      name="paywall_enabled"
                      label="启用站点访问凭据"
                      valuePropName="checked"
                      initialValue={false}
                    >
                      <Switch checkedChildren="启用" unCheckedChildren="关闭" />
                    </Form.Item>

                    <Form.Item shouldUpdate noStyle>
                      {() => {
                        const paywallEnabled = form.getFieldValue('paywall_enabled')
                        if (!paywallEnabled) return null
                        const sourceUrl: string | undefined = form.getFieldValue('url')
                        const sourceHost = normalizeHost(sourceUrl || '')
                        // Narrow the list by host if we can; otherwise show
                        // everything so users of exotic multi-host setups
                        // aren't stuck (backend tolerates either way).
                        const matchingConfigs = sourceHost
                          ? websiteAuthConfigs.filter((cfg) => {
                              const cfgHost = normalizeHost(cfg.site_url)
                              if (!cfgHost) return false
                              return (
                                sourceHost === cfgHost ||
                                sourceHost.endsWith(`.${cfgHost}`) ||
                                cfgHost.endsWith(`.${sourceHost}`)
                              )
                            })
                          : websiteAuthConfigs
                        const matchingBrowserSessions = sourceHost
                          ? activeWebsiteBrowserSessions.filter((session) => {
                              const sessionHost = normalizeHost(
                                session.site_host || session.site_url,
                              )
                              if (!sessionHost) return false
                              return (
                                sourceHost === sessionHost ||
                                sourceHost.endsWith(`.${sessionHost}`) ||
                                sessionHost.endsWith(`.${sourceHost}`)
                              )
                            })
                          : activeWebsiteBrowserSessions
                        const hasMatching =
                          matchingConfigs.length > 0 || matchingBrowserSessions.length > 0
                        return (
                          <>
                            <SectionNote style={{ marginBottom: 12 }}>
                              登录态统一在「登录与凭据」页管理：为该站点创建浏览器会话后，登录一次即可长期复用；这里只需把监控源挂到已有凭据上。
                            </SectionNote>
                            <Form.Item
                              name="website_auth_config_id"
                              label="站点凭据"
                              rules={[{ required: true, message: '请选择一份已有的站点凭据' }]}
                            >
                              <Select
                                allowClear
                                placeholder={
                                  hasMatching
                                    ? '选择一份已有的站点凭据'
                                    : '当前站点暂无已保存凭据，请先到「登录与凭据」创建'
                                }
                                notFoundContent="没有匹配的站点凭据"
                                options={[
                                  ...matchingBrowserSessions.map((session) => ({
                                    value: browserSessionCredentialValue(session.id),
                                    label: `${session.site_host} · 浏览器登录态 · 已验证${
                                      session.bound_sources
                                        ? ` · 已被 ${session.bound_sources} 个源使用`
                                        : ''
                                    }`,
                                  })),
                                  ...matchingConfigs.map((config) => ({
                                    value: config.id,
                                    label: `${getAuthConfigDisplayName(config)}${
                                      config.cookie_count ? ` · ${config.cookie_count} 项 Cookie` : ''
                                    }${config.bound_source_count ? ` · 已被 ${config.bound_source_count} 个源使用` : ''}`,
                                  })),
                                ]}
                              />
                            </Form.Item>
                            {!hasMatching ? (
                              <SectionNote tone="caution" style={{ marginBottom: 12 }}>
                                还没有可复用的凭据。请先到{' '}
                                <Link to="/settings?tab=credentials" target="_blank" rel="noreferrer">
                                  「登录与凭据」
                                </Link>{' '}
                                为该站点创建浏览器会话或补充凭据。
                              </SectionNote>
                            ) : null}
                          </>
                        )
                      }}
                    </Form.Item>
                  </>
                )}
              </>
            )
          }}
        </Form.Item>

        <Divider style={{ marginTop: 8, marginBottom: 12 }}>信源质量</Divider>

        <SectionNote style={{ marginBottom: 12 }}>
          星级会影响评分中的「权威性」维度；信源权重仅作为少量人工校准，通常保持 1。
        </SectionNote>

        <Form.Item
          name="source_stars"
          label="信源星级"
          initialValue={1}
        >
          <Select
            options={[
              { value: 3, label: '三星 · 官方信源 / 权威媒体 / 一手信源' },
              { value: 2, label: '二星 · 普通媒体 / 优质自媒体' },
              { value: 1, label: '一星 · 聚合媒体 / 泛资讯平台 / 普通个人作者' },
            ]}
          />
        </Form.Item>

        <Form.Item
          name="source_weight"
          label="信源权重"
          initialValue={1}
          tooltip="用于最终分数微调。建议保持 1；只有非常确定的高/低质量源才调整。"
        >
          <InputNumber min={0.5} max={1.5} step={0.05} style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item shouldUpdate noStyle>
          {() => {
            if (form.getFieldValue('type') !== 'website') return null
            return (
              <>
                <Divider style={{ marginTop: 8, marginBottom: 12 }}>抓取策略</Divider>
                <SectionNote style={{ marginBottom: 12 }}>
                  系统会先使用稳定、低干扰的方式抓取；遇到动态渲染、访问限制或正文缺失时，
                  再自动尝试 RSS、已绑定的登录态、浏览器渲染和兼容策略。无需手动选择技术参数，
                  最终结果和失败原因会显示在信源状态中。
                </SectionNote>
              </>
            )
          }}
        </Form.Item>

        <Form.Item
          name="use_keyword_filter"
          label="仅保存命中关键词的内容"
          valuePropName="checked"
          initialValue={false}
          tooltip="开启后，只有标题或正文匹配至少一个关键词的内容才会被保存。需先在「设置 → 关键词管理」中配置关键词。"
        >
          <Switch checkedChildren="开启" unCheckedChildren="关闭" />
        </Form.Item>

        <Form.Item shouldUpdate noStyle>
          {() => {
            const filterEnabled = form.getFieldValue('use_keyword_filter')
            if (!filterEnabled) return null
            return (
              <SectionNote style={{ marginBottom: 12 }}>
                当前源只会保留命中关键词的内容；未匹配的内容会被跳过。请先在「设置 → 关键词管理」里配置好关键词。
              </SectionNote>
            )
          }}
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
