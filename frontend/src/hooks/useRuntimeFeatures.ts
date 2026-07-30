import { useEffect, useState } from 'react'

import { systemApi, type RuntimeFeatures } from '../services/system'

let cachedFeatures: RuntimeFeatures | null = null
let pendingRequest: Promise<RuntimeFeatures> | null = null

function loadFeatures(): Promise<RuntimeFeatures> {
  if (cachedFeatures) return Promise.resolve(cachedFeatures)
  if (!pendingRequest) {
    pendingRequest = systemApi.getFeatures().then((features) => {
      cachedFeatures = features
      return features
    }).finally(() => {
      pendingRequest = null
    })
  }
  return pendingRequest
}

/** Small runtime-profile hook that also works in isolated component tests. */
export function useRuntimeFeatures(): RuntimeFeatures | null {
  const [features, setFeatures] = useState<RuntimeFeatures | null>(cachedFeatures)

  useEffect(() => {
    let active = true
    void loadFeatures()
      .then((value) => {
        if (active) setFeatures(value)
      })
      .catch(() => {
        // A missing backend must not block the normal consumption UI.
      })
    return () => {
      active = false
    }
  }, [])

  return features
}
