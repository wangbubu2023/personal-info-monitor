import { useState } from 'react'
import { Form, message } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { sourcesApi } from '../../../services/sources'
import { type AuthConfig } from '../../../services/configs'
import { sourceKeys } from '../../../services/queryKeys'
import type { Source, SourceCreate, SourceType } from '../../../types'
import { parseUrlLines } from '../importUtils'
import { normalizeHost, isXCookieProfile } from '../../../utils/sourceAuth'
import {
  getAxiosErrorMessage,
  isAxiosTimeout,
  isDuplicateSourceError,
} from '../../../utils/apiError'
import { normalizeSourceUrl } from '../../../utils/sourceUrl'

export interface SourceFormValues extends Omit<SourceCreate, 'extra_urls'> {
  extra_urls_text?: string
  /** 抓取回溯时间（分钟）；留空表示使用全局默认 60；写入 metadata.max_fetch_lag_minutes */
  max_fetch_lag_minutes?: number | null
  paywall_enabled?: boolean
  /** 用户为 website 源选中的已有 auth_config.id；监控源编辑弹窗里的唯一凭据入口。 */
  website_auth_config_id?: string
  /**
   * "仅 RSS 摘要" 开关：true 时跳过全文抓取（Playwright hydration），只保留
   * RSS 摘要。写入 metadata.rss_only，用于被 DataDome 等反爬系统挡住的源。
   */
  rss_only_enabled?: boolean
  source_stars?: number
  authority_type?: string
  domain_focus_text?: string
  source_weight?: number
  x_cookie_enabled?: boolean
  x_shared_auth_config_id?: string
  x_legacy_dedicated_auth?: boolean
  x_legacy_auth_name?: string
}

interface UseSourceEditorOptions {
  authConfigs: AuthConfig[]
  sourceLimitReached: boolean
  maxSources: number
  defaultSharedXAuthConfigId: string | undefined
}

export function useSourceEditor({
  authConfigs,
  sourceLimitReached,
  maxSources,
  defaultSharedXAuthConfigId,
}: UseSourceEditorOptions) {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingSource, setEditingSource] = useState<Source | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [form] = Form.useForm<SourceFormValues>()
  const queryClient = useQueryClient()

  const invalidateSources = () => queryClient.invalidateQueries({ queryKey: sourceKeys.all })

  const createMutation = useMutation({
    mutationFn: sourcesApi.create,
    onSuccess: () => {
      setSubmitError(null)
      invalidateSources()
      message.success('创建成功')
      setIsModalOpen(false)
      form.resetFields()
    },
    onError: (error: unknown) => {
      if (isDuplicateSourceError(error)) {
        setSubmitError(null)
        invalidateSources()
        message.info(getAxiosErrorMessage(error, '该信源已存在'))
        setIsModalOpen(false)
        form.resetFields()
        return
      }
      const detail = getAxiosErrorMessage(error, '创建失败，请检查输入后重试。')
      if (isAxiosTimeout(error)) {
        invalidateSources()
      }
      setSubmitError(detail)
      message.error(detail.startsWith('创建') ? detail : `创建失败：${detail}`)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<SourceCreate> }) =>
      sourcesApi.update(id, data),
    onSuccess: () => {
      setSubmitError(null)
      invalidateSources()
      message.success('更新成功')
      setIsModalOpen(false)
      setEditingSource(null)
      form.resetFields()
    },
    onError: (error: unknown) => {
      const detail = getAxiosErrorMessage(error, '更新失败，请检查输入后重试。')
      setSubmitError(detail)
      message.error(detail.startsWith('更新') ? detail : `更新失败：${detail}`)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: sourcesApi.delete,
    onSuccess: () => { invalidateSources(); message.success('删除成功') },
    onError: () => { message.error('删除失败') },
  })

  const fetchMutation = useMutation({
    mutationFn: sourcesApi.triggerFetch,
    onSuccess: () => { message.success('已触发抓取任务') },
    onError: () => { message.error('触发失败') },
  })

  const probeMutation = useMutation({
    mutationFn: sourcesApi.probeSource,
    onSuccess: () => { invalidateSources(); message.success('探测完成') },
    onError: () => { message.error('探测失败') },
  })

  const probeAllMutation = useMutation({
    mutationFn: sourcesApi.probeAll,
    onSuccess: (data) => { invalidateSources(); message.success(`已探测 ${data.total} 个源`) },
    onError: () => { message.error('批量探测失败') },
  })

  const matchAuthConfigByHost = (url: string, configs: AuthConfig[] = []): AuthConfig | undefined => {
    const sourceHost = normalizeHost(url)
    if (!sourceHost) return undefined
    return configs.find((cfg) => {
      const cfgHost = normalizeHost(cfg.site_url)
      return !!cfgHost && (
        sourceHost === cfgHost ||
        sourceHost.endsWith(`.${cfgHost}`) ||
        cfgHost.endsWith(`.${sourceHost}`)
      )
    })
  }

  const handleSubmit = async (values: SourceFormValues) => {
    setSubmitError(null)
    const {
      extra_urls_text,
      paywall_enabled,
      website_auth_config_id,
      rss_only_enabled,
      source_stars,
      authority_type,
      domain_focus_text,
      source_weight,
      x_cookie_enabled,
      x_shared_auth_config_id,
      max_fetch_lag_minutes,
      metadata: formMetadata,
      ...rest
    } = values

    const baseMeta: Record<string, unknown> =
      typeof formMetadata === 'object' && formMetadata !== null ? { ...formMetadata } : {}
    if (max_fetch_lag_minutes != null) {
      const n = Number(max_fetch_lag_minutes)
      if (!Number.isNaN(n)) {
        baseMeta.max_fetch_lag_minutes = n
      }
    } else if (editingSource) {
      baseMeta.max_fetch_lag_minutes = null
    } else {
      delete baseMeta.max_fetch_lag_minutes
    }

    const stars = Number(source_stars)
    baseMeta.source_stars = Number.isFinite(stars) ? Math.max(1, Math.min(3, Math.round(stars))) : 1
    if (authority_type && authority_type.trim()) {
      baseMeta.authority_type = authority_type.trim()
    } else if (editingSource) {
      baseMeta.authority_type = ''
    } else {
      delete baseMeta.authority_type
    }
    const domainFocus = parseUrlLines((domain_focus_text || '').replace(/[,，、]/g, '\n'))
      .map((x) => x.replace(/^https?:\/\//i, '').trim())
      .filter(Boolean)
    if (domainFocus.length > 0) {
      baseMeta.domain_focus = domainFocus
    } else if (editingSource) {
      baseMeta.domain_focus = []
    } else {
      delete baseMeta.domain_focus
    }
    const weight = Number(source_weight)
    if (Number.isFinite(weight)) {
      baseMeta.source_weight = Math.max(0.5, Math.min(1.5, weight))
    } else if (editingSource) {
      baseMeta.source_weight = 1
    }

    // Persist the "仅 RSS 摘要" toggle as a boolean flag inside metadata. The
    // hydration fallback only exists on the website collector path (RSS /
    // YouTube / X / podcast use dedicated collectors without hydration), so
    // we only emit this flag for website sources and drop it everywhere else
    // to keep metadata clean.
    if (rest.type === 'website') {
      if (rss_only_enabled) {
        baseMeta.rss_only = true
      } else if (editingSource && baseMeta.rss_only) {
        // User toggled it off on an existing source → explicitly clear.
        baseMeta.rss_only = false
      } else {
        delete baseMeta.rss_only
      }
    } else {
      delete baseMeta.rss_only
    }

    const payload: SourceCreate = {
      ...rest,
      url: normalizeSourceUrl(rest.url),
      metadata: baseMeta,
      extra_urls: parseUrlLines(extra_urls_text).map(normalizeSourceUrl).filter(Boolean),
    }

    if (!editingSource && sourceLimitReached) {
      setSubmitError(`监控源已达上限（${maxSources}），请先删除部分信源再添加。`)
      message.warning(`监控源已达上限（${maxSources}），请先删除部分信源再添加。`)
      return
    }

    try {
      if (payload.type === 'website') {
        const enablePaywall = Boolean(paywall_enabled)
        if (enablePaywall) {
          // The editor no longer creates/updates AuthConfig rows — users
          // manage credentials in the dedicated "登录与凭据" tab. Here we just
          // bind the source to whichever existing config they picked.
          const selectedId = website_auth_config_id
          if (!selectedId) {
            setSubmitError('请先在「登录与凭据」页为该站点创建凭据，再在下拉框中选择。')
            message.error('保存失败：请选择一份已有的站点凭据')
            return
          }
          const exists = (authConfigs || []).some((cfg) => cfg.id === selectedId)
          if (!exists) {
            setSubmitError('所选凭据已不存在，请到「登录与凭据」页刷新后重选。')
            message.error('保存失败：所选凭据已不存在')
            return
          }
          payload.auth_required = true
          payload.auth_config_id = selectedId
        } else {
          payload.auth_required = false
          ;(payload as SourceCreate & { auth_config_id: string | null }).auth_config_id = null
        }
      } else if (payload.type === 'x') {
        const enableXCredential = Boolean(x_cookie_enabled)
        const existingLinkedAuth = authConfigs?.find((cfg) => cfg.id === editingSource?.auth_config_id)
        const canReuseLegacyDedicated = Boolean(
          existingLinkedAuth && !existingLinkedAuth.is_shared && isXCookieProfile(existingLinkedAuth)
        )

        if (enableXCredential) {
          if (x_shared_auth_config_id) {
            payload.auth_required = true
            payload.auth_config_id = x_shared_auth_config_id
          } else if (canReuseLegacyDedicated) {
            payload.auth_required = true
            payload.auth_config_id = existingLinkedAuth!.id
          } else {
            setSubmitError('请先到“访问凭据”页配置共享 X 登录态，或关闭“复用 X 访问凭据”。')
            message.error('保存失败：请先到“访问凭据”页配置共享 X 登录态')
            return
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
      const detail = getAxiosErrorMessage(error, '认证配置未更新，请稍后重试。')
      setSubmitError(detail)
      message.error(detail.startsWith('保存') ? detail : `保存失败：${detail}`)
    }
  }

  const handleEdit = (source: Source) => {
    setSubmitError(null)
    const linkedAuth =
      authConfigs?.find((cfg) => cfg.id === source.auth_config_id) ||
      (source.type === 'website' ? matchAuthConfigByHost(source.url, authConfigs || []) : undefined)
    setEditingSource(source)
    const xUsesLegacyDedicatedAuth = Boolean(
      source.type === 'x' && linkedAuth && !linkedAuth.is_shared && isXCookieProfile(linkedAuth)
    )
    const lag = source.metadata?.max_fetch_lag_minutes
    const domainFocus = Array.isArray(source.metadata?.domain_focus)
      ? (source.metadata?.domain_focus as unknown[]).map((x) => String(x)).join('\n')
      : typeof source.metadata?.domain_focus === 'string'
        ? String(source.metadata.domain_focus)
        : ''
    const rssOnlyFromMeta = Boolean(
      source.type === 'website' && source.metadata?.rss_only
    )
    form.setFieldsValue({
      ...source,
      metadata: source.metadata as any,
      source_stars: Number(source.metadata?.source_stars || 1),
      authority_type: typeof source.metadata?.authority_type === 'string' ? source.metadata.authority_type : undefined,
      domain_focus_text: domainFocus,
      source_weight:
        source.metadata?.source_weight !== undefined && source.metadata?.source_weight !== null
          ? Number(source.metadata.source_weight)
          : 1,
      max_fetch_lag_minutes:
        lag !== undefined && lag !== null && lag !== '' ? Number(lag) : undefined,
      extra_urls_text: (source.extra_urls || []).join('\n'),
      paywall_enabled: Boolean(source.auth_required || source.auth_config_id || linkedAuth),
      website_auth_config_id:
        source.type === 'website' ? linkedAuth?.id || undefined : undefined,
      rss_only_enabled: rssOnlyFromMeta,
      x_cookie_enabled: Boolean(source.type === 'x' && (source.auth_required || source.auth_config_id || linkedAuth)),
      x_shared_auth_config_id:
        source.type === 'x' && linkedAuth?.is_shared ? linkedAuth.id : defaultSharedXAuthConfigId,
      x_legacy_dedicated_auth: xUsesLegacyDedicatedAuth,
      x_legacy_auth_name: xUsesLegacyDedicatedAuth ? linkedAuth?.name || undefined : undefined,
    })
    setIsModalOpen(true)
  }

  const handleAdd = () => {
    if (sourceLimitReached) {
      setSubmitError(`监控源已达上限（${maxSources}），请先删除部分信源再添加。`)
      message.warning(`监控源已达上限（${maxSources}），请先删除部分信源再添加。`)
      return
    }
    setSubmitError(null)
    setEditingSource(null)
    form.resetFields()
    form.setFieldsValue({
      paywall_enabled: false,
      website_auth_config_id: undefined,
      rss_only_enabled: false,
      source_stars: 1,
      authority_type: undefined,
      domain_focus_text: '',
      source_weight: 1,
      x_cookie_enabled: true,
      x_shared_auth_config_id: defaultSharedXAuthConfigId,
      x_legacy_dedicated_auth: false,
      x_legacy_auth_name: undefined,
    })
    setIsModalOpen(true)
  }

  const handleTypeChange = (nextType: SourceType) => {
    setSubmitError(null)
    if (editingSource) return
    if (nextType === 'x') {
      form.setFieldsValue({
        x_cookie_enabled: true,
        x_shared_auth_config_id: defaultSharedXAuthConfigId,
        x_legacy_dedicated_auth: false,
        x_legacy_auth_name: undefined,
        website_auth_config_id: undefined,
      })
      return
    }
    form.setFieldsValue({
      x_cookie_enabled: false,
      x_shared_auth_config_id: undefined,
      x_legacy_dedicated_auth: false,
      x_legacy_auth_name: undefined,
      website_auth_config_id: undefined,
    })
  }

  return {
    isModalOpen,
    setIsModalOpen,
    editingSource,
    setEditingSource,
    submitError,
    setSubmitError,
    form,
    createMutation,
    updateMutation,
    deleteMutation,
    fetchMutation,
    probeMutation,
    probeAllMutation,
    handleSubmit,
    handleEdit,
    handleAdd,
    handleTypeChange,
    matchAuthConfigByHost,
  }
}
