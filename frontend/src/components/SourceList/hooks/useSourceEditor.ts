import { useState } from 'react'
import { Form, message } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { sourcesApi } from '../../../services/sources'
import { configsApi, type AuthConfig } from '../../../services/configs'
import { sourceKeys } from '../../../services/queryKeys'
import type { Source, SourceCreate, SourceType } from '../../../types'
import { parseUrlLines } from '../importUtils'
import {
  normalizeHost,
  resolveSiteUrlForAuth,
  isXCookieProfile,
  getAuthConfigDisplayName,
} from '../../../utils/sourceAuth'

export { getAuthConfigDisplayName }

interface SourceFormValues extends Omit<SourceCreate, 'extra_urls'> {
  extra_urls_text?: string
  paywall_enabled?: boolean
  x_cookie_enabled?: boolean
  x_auth_mode?: 'shared' | 'dedicated'
  x_shared_auth_config_id?: string
  x_auth_name?: string
  auth_type?: string
  login_url?: string
  username?: string
  password?: string
  cookies?: string
  x_auth_token?: string
  x_ct0?: string
}

interface UseSourceEditorOptions {
  authConfigs: AuthConfig[]
  sourceLimitReached: boolean
  maxSources: number
  remainingSources: number
  sharedXAuthConfigs: AuthConfig[]
  defaultSharedXAuthConfigId: string | undefined
}

export function useSourceEditor({
  authConfigs,
  sourceLimitReached,
  maxSources,
  sharedXAuthConfigs,
  defaultSharedXAuthConfigId,
}: UseSourceEditorOptions) {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingSource, setEditingSource] = useState<Source | null>(null)
  const [form] = Form.useForm<SourceFormValues>()
  const queryClient = useQueryClient()

  const invalidateSources = () => queryClient.invalidateQueries({ queryKey: sourceKeys.all })

  const createMutation = useMutation({
    mutationFn: sourcesApi.create,
    onSuccess: () => {
      invalidateSources()
      message.success('创建成功')
      setIsModalOpen(false)
      form.resetFields()
    },
    onError: (error: unknown) => {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail ? `创建失败：${detail}` : '创建失败')
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<SourceCreate> }) =>
      sourcesApi.update(id, data),
    onSuccess: () => {
      invalidateSources()
      message.success('更新成功')
      setIsModalOpen(false)
      setEditingSource(null)
      form.resetFields()
    },
    onError: (error: unknown) => {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail ? `更新失败：${detail}` : '更新失败')
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
    const {
      extra_urls_text,
      paywall_enabled,
      x_cookie_enabled,
      x_auth_mode,
      x_shared_auth_config_id,
      x_auth_name,
      auth_type,
      login_url,
      username,
      password,
      cookies,
      x_auth_token,
      x_ct0,
      ...rest
    } = values

    const payload: SourceCreate = {
      ...rest,
      extra_urls: parseUrlLines(extra_urls_text),
    }

    if (!editingSource && sourceLimitReached) {
      message.warning(`监控源已达上限（${maxSources}），请先删除部分信源再添加。`)
      return
    }

    try {
      if (payload.type === 'website') {
        const enablePaywall = Boolean(paywall_enabled)
        if (enablePaywall) {
          const site_url = resolveSiteUrlForAuth(payload.url)
          let targetAuth =
            authConfigs?.find((cfg) => cfg.id === editingSource?.auth_config_id) ||
            matchAuthConfigByHost(payload.url, authConfigs || [])

          const authPayload = {
            site_url,
            auth_type: auth_type || 'password',
            login_url: login_url || undefined,
            username: username || undefined,
            password: password || undefined,
            cookies: cookies || undefined,
          }

          if (targetAuth) {
            await configsApi.updateAuthConfig(targetAuth.id, authPayload)
          } else {
            targetAuth = await configsApi.createAuthConfig(authPayload)
          }
          await queryClient.invalidateQueries({ queryKey: ['auth-configs'] })

          payload.auth_required = true
          payload.auth_config_id = targetAuth.id
        } else {
          payload.auth_required = false
          ;(payload as SourceCreate & { auth_config_id: string | null }).auth_config_id = null
        }
      } else if (payload.type === 'x') {
        const enableXCookie = Boolean(x_cookie_enabled)
        if (enableXCookie) {
          const selectedMode = x_auth_mode || (sharedXAuthConfigs.length > 0 ? 'shared' : 'dedicated')
          if (selectedMode === 'shared') {
            if (!x_shared_auth_config_id) {
              message.error('保存失败：请选择一个共享 X 登录态')
              return
            }
            payload.auth_required = true
            payload.auth_config_id = x_shared_auth_config_id
          } else {
            const existingLinkedAuth = authConfigs?.find((cfg) => cfg.id === editingSource?.auth_config_id)
            const canReuseExistingDedicated = Boolean(
              existingLinkedAuth && !existingLinkedAuth.is_shared && isXCookieProfile(existingLinkedAuth)
            )
            const authToken = (x_auth_token || '').trim()
            const ct0 = (x_ct0 || '').trim()
            const profileName = (x_auth_name || '').trim()
            const hasCookieUpdate = Boolean(authToken || ct0)

            if (hasCookieUpdate && (!authToken || !ct0)) {
              message.error('保存失败：请同时填写 auth_token 和 ct0')
              return
            }
            if (!hasCookieUpdate && !canReuseExistingDedicated) {
              message.error('保存失败：请填写专用 X 登录态的 auth_token 和 ct0')
              return
            }

            let savedAuth = existingLinkedAuth
            if (hasCookieUpdate) {
              const authPayload = {
                name: profileName || existingLinkedAuth?.name || `${payload.name} 专用 X 登录态`,
                site_url: 'https://x.com',
                auth_type: 'cookie',
                is_shared: false,
                cookies: { auth_token: authToken, ct0 },
              }
              savedAuth = canReuseExistingDedicated
                ? await configsApi.updateAuthConfig(existingLinkedAuth!.id, authPayload)
                : await configsApi.createAuthConfig(authPayload)
              await queryClient.invalidateQueries({ queryKey: ['auth-configs'] })
            }

            payload.auth_required = true
            payload.auth_config_id = savedAuth?.id
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
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail ? `保存失败：${detail}` : '保存失败：认证配置未更新')
    }
  }

  const handleEdit = (source: Source) => {
    const linkedAuth =
      authConfigs?.find((cfg) => cfg.id === source.auth_config_id) ||
      (source.type === 'website' ? matchAuthConfigByHost(source.url, authConfigs || []) : undefined)
    setEditingSource(source)
    const xMode: 'shared' | 'dedicated' | undefined =
      source.type === 'x'
        ? linkedAuth?.is_shared
          ? 'shared'
          : linkedAuth
            ? 'dedicated'
            : sharedXAuthConfigs.length > 0
              ? 'shared'
              : 'dedicated'
        : undefined
    form.setFieldsValue({
      ...source,
      extra_urls_text: (source.extra_urls || []).join('\n'),
      paywall_enabled: Boolean(source.auth_required || source.auth_config_id || linkedAuth),
      x_cookie_enabled: Boolean(source.type === 'x' && (source.auth_required || source.auth_config_id || linkedAuth)),
      x_auth_mode: xMode,
      x_shared_auth_config_id: xMode === 'shared' ? linkedAuth?.id : undefined,
      x_auth_name: !linkedAuth?.is_shared ? linkedAuth?.name || undefined : undefined,
      auth_type: linkedAuth?.auth_type || 'password',
      login_url: linkedAuth?.login_url || undefined,
      username: undefined,
      password: undefined,
      cookies: undefined,
      x_auth_token: undefined,
      x_ct0: undefined,
    })
    setIsModalOpen(true)
  }

  const handleAdd = () => {
    if (sourceLimitReached) {
      message.warning(`监控源已达上限（${maxSources}），请先删除部分信源再添加。`)
      return
    }
    setEditingSource(null)
    form.resetFields()
    form.setFieldsValue({
      paywall_enabled: false,
      x_cookie_enabled: sharedXAuthConfigs.length > 0,
      x_auth_mode: sharedXAuthConfigs.length > 0 ? 'shared' : 'dedicated',
      x_shared_auth_config_id: defaultSharedXAuthConfigId,
      auth_type: 'password',
    })
    setIsModalOpen(true)
  }

  const handleTypeChange = (nextType: SourceType) => {
    if (editingSource) return
    if (nextType === 'x') {
      form.setFieldsValue({
        x_cookie_enabled: sharedXAuthConfigs.length > 0,
        x_auth_mode: sharedXAuthConfigs.length > 0 ? 'shared' : 'dedicated',
        x_shared_auth_config_id: defaultSharedXAuthConfigId,
      })
      return
    }
    form.setFieldsValue({
      x_cookie_enabled: false,
      x_auth_mode: sharedXAuthConfigs.length > 0 ? 'shared' : 'dedicated',
      x_shared_auth_config_id: undefined,
      x_auth_name: undefined,
      x_auth_token: undefined,
      x_ct0: undefined,
    })
  }

  return {
    isModalOpen,
    setIsModalOpen,
    editingSource,
    setEditingSource,
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
