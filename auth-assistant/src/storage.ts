import type { RemoteConnection } from './api'

const CONNECTIONS_KEY = 'pim-auth-assistant.connections'
const ACTIVE_CONNECTION_KEY = 'pim-auth-assistant.activeConnectionId'
const LEGACY_CONNECTION_KEY = 'pim-auth-assistant.connection'
const BUNDLES_KEY = 'pim-auth-assistant.bundles'

export interface SavedBundle {
  id: string
  name: string
  siteHost: string
  capturedAt: string
  bundle: unknown
}

export interface SavedConnection extends RemoteConnection {
  id: string
  label: string
}

function withConnectionId(connection: RemoteConnection & Partial<SavedConnection>): SavedConnection {
  const serverUrl = connection.serverUrl.replace(/\/+$/, '')
  return {
    ...connection,
    serverUrl,
    id: connection.id || `${serverUrl}::${connection.deviceName}`,
    label: connection.label || serverUrl,
  }
}

export function loadConnections(): SavedConnection[] {
  const raw = localStorage.getItem(CONNECTIONS_KEY)
  let parsed: unknown = null
  if (raw) {
    try {
      parsed = JSON.parse(raw)
    } catch {
      parsed = null
    }
  }
  if (Array.isArray(parsed)) {
    return parsed.map((item) => withConnectionId(item as SavedConnection))
  }

  const legacyRaw = localStorage.getItem(LEGACY_CONNECTION_KEY)
  if (!legacyRaw) return []
  try {
    const legacy = withConnectionId(JSON.parse(legacyRaw) as RemoteConnection)
    localStorage.setItem(CONNECTIONS_KEY, JSON.stringify([legacy]))
    localStorage.setItem(ACTIVE_CONNECTION_KEY, legacy.id)
    localStorage.removeItem(LEGACY_CONNECTION_KEY)
    return [legacy]
  } catch {
    return []
  }
}

export function loadActiveConnectionId(): string | null {
  return localStorage.getItem(ACTIVE_CONNECTION_KEY)
}

export function saveActiveConnectionId(id: string | null): void {
  if (id) localStorage.setItem(ACTIVE_CONNECTION_KEY, id)
  else localStorage.removeItem(ACTIVE_CONNECTION_KEY)
}

export function getActiveConnection(connections = loadConnections()): SavedConnection | null {
  const activeId = loadActiveConnectionId()
  return connections.find((item) => item.id === activeId) || connections[0] || null
}

export function saveConnection(connection: RemoteConnection & Partial<SavedConnection>): SavedConnection[] {
  const normalized = withConnectionId(connection)
  const next = [normalized, ...loadConnections().filter((item) => item.id !== normalized.id)]
  localStorage.setItem(CONNECTIONS_KEY, JSON.stringify(next))
  localStorage.setItem(ACTIVE_CONNECTION_KEY, normalized.id)
  return next
}

export function deleteConnection(id: string): SavedConnection[] {
  const next = loadConnections().filter((item) => item.id !== id)
  localStorage.setItem(CONNECTIONS_KEY, JSON.stringify(next))
  if (loadActiveConnectionId() === id) {
    saveActiveConnectionId(next[0]?.id || null)
  }
  return next
}

export function loadBundles(): SavedBundle[] {
  const raw = localStorage.getItem(BUNDLES_KEY)
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function saveBundle(bundle: SavedBundle): SavedBundle[] {
  const next = [bundle, ...loadBundles().filter((item) => item.id !== bundle.id)]
  localStorage.setItem(BUNDLES_KEY, JSON.stringify(next))
  return next
}

export function deleteBundle(id: string): SavedBundle[] {
  const next = loadBundles().filter((item) => item.id !== id)
  localStorage.setItem(BUNDLES_KEY, JSON.stringify(next))
  return next
}
