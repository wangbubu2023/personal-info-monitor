import { useState } from 'react'
import { Form, message } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { sourcesApi } from '../../../services/sources'
import { type AuthConfig } from '../../../services/configs'
import type { BrowserSession } from '../../../services/browserSessions'
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
  max_fetch_lag_minutes?: number | null
  paywall_enabled?: boolean
  /** 用户为 website 源选中的 AuthConfig id 或 browser-session:<id>。 */
  website_auth_config_id?: string
  source_stars?: number
  authority_type?: string
  source_weight?: number
  x_cookie_enabled?: boolean
  x_shared_auth_config_id?: string
  x_legacy_dedicated_auth?: boolean
  x_legacy_auth_name?: string
}

interface UseSourceEditorOptions {
  authConfigs: AuthConfig[]
  browserSessions?: BrowserSession[]
  sourceLimitReached: boolean
  maxSources: number
  defaultSharedXAuthConfigId: string | undefined
}

export const BROWSER_SESSION_CREDENTIAL_PREFIX = 'browser-session:'
const LEGACY_WEBSITE_STRATEGY_KEYS = [
  'rss_only',
  'bpc_spoof_ua',
  'bpc_spoof_referer',
  'bpc_random_ip',
  'bpc_block_paywalls',
  'bpc_ephemeral_context',
] as const

export function browserSessionCredentialValue(id: string): string {
  return `${BROWSER_SESSION_CREDENTIAL_PREFIX}${id}`
}

function browserSessionIdFromCredentialValue(value?: string): string | undefined {
  if (!value?.startsWith(BROWSER_SESSION_CREDENTIAL_PREFIX)) return undefined
  const id = value.slice(BROWSER_SESSION_CREDENTIAL_PREFIX.length).trim()
  return id || undefined
}

export function useSourceEditor({
  authConfigs,
  browserSessions = [],
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
      source_stars,
      authority_type,
      source_weight,
      x_cookie_enabled,
      x_shared_auth_config_id,
      max_fetch_lag_minutes,
      metadata: formMetadata,
      ...rest
    } = values

    const baseMeta: Record<string, unknown> =
      typeof formMetadata === 'object' && formMetadata !== null ? { ...formMetadata } : {}
    const clearBrowserSessionBinding = () => {
      if (editingSource && baseMeta.browser_session_id) {
        // Source updates merge metadata, so null is the explicit tombstone for
        // a previously persisted browser-session binding.
        baseMeta.browser_session_id = null
      } else {
        delete baseMeta.browser_session_id
      }
    }
    void authority_type
    void max_fetch_lag_minutes

    const stars = Number(source_stars)
    baseMeta.source_stars = Number.isFinite(stars) ? Math.max(1, Math.min(3, Math.round(stars))) : 1
    const weight = Number(source_weight)
    if (Number.isFinite(weight)) {
      baseMeta.source_weight = Math.max(0.5, Math.min(1.5, weight))
    } else if (editingSource) {
      baseMeta.source_weight = 1
    }

    if (rest.type === 'website') {
      LEGACY_WEBSITE_STRATEGY_KEYS.forEach((key) => delete baseMeta[key])
      baseMeta.fetch_strategy_mode = 'auto'
    } else {
      LEGACY_WEBSITE_STRATEGY_KEYS.forEach((key) => delete baseMeta[key])
      delete baseMeta.fetch_strategy_mode
      clearBrowserSessionBinding()
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
          const selectedId = website_auth_config_id
          if (!selectedId) {
            setSubmitError('请先在「登录与凭据」页为该站点创建凭据，再在下拉框中选择。')
            message.error('保存失败：请选择一份已有的站点凭据')
            return
          }
          const browserSessionId = browserSessionIdFromCredentialValue(selectedId)
          if (browserSessionId) {
            const session = browserSessions.find(
              (item) => item.id === browserSessionId && item.status === 'active',
            )
            if (!session) {
              setSubmitError('所选浏览器登录态已失效或不存在，请重新登录后再选择。')
              message.error('保存失败：所选浏览器登录态不可用')
              return
            }
            payload.auth_required = true
            payload.auth_config_id = null
            baseMeta.browser_session_id = session.id
          } else {
            const exists = (authConfigs || []).some((cfg) => cfg.id === selectedId)
            if (!exists) {
              setSubmitError('所选凭据已不存在，请到「登录与凭据」页刷新后重选。')
              message.error('保存失败：所选凭据已不存在')
              return
            }
            payload.auth_required = true
            payload.auth_config_id = selectedId
            clearBrowserSessionBinding()
          }
        } else {
          payload.auth_required = false
          ;(payload as SourceCreate & { auth_config_id: string | null }).auth_config_id = null
          clearBrowserSessionBinding()
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
    const linkedBrowserSessionId =
      typeof source.metadata?.browser_session_id === 'string'
        ? source.metadata.browser_session_id
        : undefined
    const linkedBrowserSession = linkedBrowserSessionId
      ? browserSessions.find((session) => session.id === linkedBrowserSessionId)
      : undefined
    const linkedAuth =
      authConfigs?.find((cfg) => cfg.id === source.auth_config_id) ||
      (source.type === 'website' ? matchAuthConfigByHost(source.url, authConfigs || []) : undefined)
    setEditingSource(source)
    const xUsesLegacyDedicatedAuth = Boolean(
      source.type === 'x' && linkedAuth && !linkedAuth.is_shared && isXCookieProfile(linkedAuth)
    )
    form.setFieldsValue({
      ...source,
      metadata: source.metadata as any,
      source_stars: Number(source.metadata?.source_stars || 1),
      source_weight:
        source.metadata?.source_weight !== undefined && source.metadata?.source_weight !== null
          ? Number(source.metadata.source_weight)
          : 1,
      extra_urls_text: (source.extra_urls || []).join('\n'),
      paywall_enabled: Boolean(
        source.auth_required || source.auth_config_id || linkedAuth || linkedBrowserSession,
      ),
      website_auth_config_id:
        source.type === 'website'
          ? linkedBrowserSession
            ? browserSessionCredentialValue(linkedBrowserSession.id)
            : linkedAuth?.id || undefined
          : undefined,
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
      source_stars: 1,
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
