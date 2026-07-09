import axios from 'axios'

export interface RemoteConnection {
  serverUrl: string
  deviceToken: string
  deviceName: string
  pairedAt: string
  serverVersion?: string | null
}

export interface PairResponse {
  device_token: string
  device: {
    id: string
    name: string
  }
  server: {
    name: string
    base_url: string
    version?: string | null
  }
  capabilities: Record<string, boolean>
}

export interface AuthBundleImportResponse {
  site_host: string
  cookie_count: number
  storage_state_imported: boolean
  bound_sources: number
  auth_config?: unknown
  browser_session?: unknown
}

export function normalizeServerUrl(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, '')
  if (!trimmed) {
    throw new Error('请填写 PIM 服务器地址')
  }
  const url = new URL(trimmed)
  if (!['http:', 'https:'].includes(url.protocol)) {
    throw new Error('服务器地址必须是 http(s) URL')
  }
  return url.toString().replace(/\/+$/, '')
}

export async function pairWithServer(params: {
  serverUrl: string
  pairingToken: string
  deviceName: string
}): Promise<RemoteConnection> {
  const serverUrl = normalizeServerUrl(params.serverUrl)
  const response = await axios.post<PairResponse>(`${serverUrl}/api/auth-assistant/pair`, {
    pairing_token: params.pairingToken.trim(),
    device_name: params.deviceName.trim() || 'PIM Auth Assistant',
    app_version: '0.1.0',
  })
  return {
    serverUrl,
    deviceToken: response.data.device_token,
    deviceName: response.data.device?.name || params.deviceName || 'PIM Auth Assistant',
    pairedAt: new Date().toISOString(),
    serverVersion: response.data.server?.version ?? null,
  }
}

export async function importBundle(connection: RemoteConnection, bundle: unknown): Promise<AuthBundleImportResponse> {
  const response = await axios.post<AuthBundleImportResponse>(
    `${connection.serverUrl}/api/auth-assistant/auth-bundles/import`,
    { bundle, bind_matching_sources: true, create_browser_session: true },
    { headers: { Authorization: `Bearer ${connection.deviceToken}` } },
  )
  return response.data
}

export async function importZip(connection: RemoteConnection, file: File): Promise<unknown> {
  const formData = new FormData()
  formData.append('file', file)
  const response = await axios.post(`${connection.serverUrl}/api/auth-assistant/auth-exports/import`, formData, {
    headers: { Authorization: `Bearer ${connection.deviceToken}` },
  })
  return response.data
}
