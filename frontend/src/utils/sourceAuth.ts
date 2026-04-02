import type { AuthConfig } from '../services/configs'

/**
 * 将任意 URL / 主机名规范化为小写裸主机名（去除 www. 前缀）。
 * 无效输入返回空字符串。
 */
export const normalizeHost = (value?: string): string => {
  try {
    if (!value) return ''
    const raw = value.includes('://') ? value : `https://${value}`
    return (new URL(raw).hostname || '').toLowerCase().replace(/^www\./, '')
  } catch {
    return ''
  }
}

/**
 * 将 URL / 主机名转换为认证用的 site_url（形如 https://example.com）。
 */
export const resolveSiteUrlForAuth = (value?: string): string => {
  const host = normalizeHost(value)
  return host ? `https://${host}` : (value || '')
}

/**
 * 判断 AuthConfig 是否为 X (Twitter) 的 Cookie 登录态。
 */
export const isXCookieProfile = (config: AuthConfig): boolean => {
  const host = normalizeHost(config.site_url)
  return config.auth_type === 'cookie' && (host === 'x.com' || host === 'twitter.com')
}

/**
 * 返回 AuthConfig 的可读显示名称。
 * 优先使用 config.name；无名称时回退为 "host · id前8位"。
 */
export const getAuthConfigDisplayName = (config: AuthConfig): string =>
  config.name?.trim() || `${normalizeHost(config.site_url) || '凭证'} · ${config.id.slice(0, 8)}`

/**
 * 从共享 X 登录态列表中返回默认选项的 id（取第一条）。
 */
export const getDefaultSharedXAuthConfigId = (configs: AuthConfig[] = []): string | undefined =>
  configs[0]?.id
