import { useQuery } from '@tanstack/react-query'
import { SCORE_LAB_BUILD_ENABLED } from '../config/features'
import { configsApi } from '../services/configs'

/** True when score lab nav/route should appear (dev build + user toggle). */
export function useScoreLabEnabled(): boolean {
  const { data: settings } = useQuery({
    queryKey: ['system-settings'],
    queryFn: configsApi.getSettings,
    enabled: SCORE_LAB_BUILD_ENABLED,
    staleTime: 60_000,
  })
  if (!SCORE_LAB_BUILD_ENABLED) return false
  return Boolean(settings?.score_lab_enabled)
}
