import api from './api'

export interface AuthAssistantPairingToken {
  pairing_token: string
  pairing_url: string
  expires_at: string
  token_hint: string
}

export interface AuthAssistantDevice {
  id: string
  name: string
  status: 'active' | 'revoked' | string
  app_version?: string | null
  last_seen_at?: string | null
  created_at?: string | null
  revoked_at?: string | null
  capabilities?: Record<string, boolean>
}

export const authAssistantApi = {
  createPairingToken: async (ttlMinutes = 10): Promise<AuthAssistantPairingToken> => {
    const response = await api.post('/auth-assistant/pairing-tokens', { ttl_minutes: ttlMinutes })
    return response.data
  },
  listDevices: async (): Promise<AuthAssistantDevice[]> => {
    const response = await api.get('/auth-assistant/devices')
    return response.data
  },
  revokeDevice: async (id: string): Promise<{ message: string; device: AuthAssistantDevice }> => {
    const response = await api.delete(`/auth-assistant/devices/${id}`)
    return response.data
  },
}
