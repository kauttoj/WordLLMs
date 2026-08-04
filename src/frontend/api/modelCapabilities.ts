/**
 * Client fetch + cache for the backend model-capabilities endpoint
 * (`GET /api/model-capabilities?provider=<p>&model=<m>`).
 *
 * Dependency order: mirrors `toolManifest.ts` — it must NOT import `./backend`
 * (circular dependency — `backend.ts` re-exports `getBackendUrl` from
 * `./config` instead, so importing from here would create a circular import).
 * Depend only on `./config` for `getBackendUrl()`.
 */

import { getBackendUrl } from './config'

export interface ModelCapability {
  provider: string
  model: string
  base_model: string | null
  supported_efforts: string[]
  default_effort: string
  source: 'override' | 'litellm' | 'inferred' | 'fallback'
  warnings: string[]
}

// Conservative fallback ladder shown when the endpoint is unreachable or the
// model is unrecognized — never a silent guess at the full ladder.
export const CONSERVATIVE_EFFORTS = ['none', 'low', 'medium', 'high']

const cache = new Map<string, ModelCapability>()

export async function fetchEffortCapability(provider: string, model: string): Promise<ModelCapability> {
  const key = `${provider}:${model}`
  const cached = cache.get(key)
  if (cached) return cached

  const res = await fetch(
    `${getBackendUrl()}/api/model-capabilities?provider=${encodeURIComponent(provider)}&model=${encodeURIComponent(model)}`,
  )
  if (!res.ok) {
    throw new Error(`Failed to load model capabilities: ${res.status} ${await res.text()}`)
  }
  const capability: ModelCapability = await res.json()
  cache.set(key, capability)
  return capability
}
