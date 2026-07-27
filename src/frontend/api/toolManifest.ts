/**
 * Client fetch + parity check for the backend tool manifest (`GET /api/tools`).
 *
 * Dependency order: this module sits between the leaf modules (`config.ts`,
 * `toolNames.ts`, `@/utils/wordTools`) and `backend.ts` / the pages. It must
 * NOT import from `./backend` — `backend.ts` re-exports `getBackendUrl` from
 * `./config` instead, so importing from here would create a circular import.
 */

import { wordToolExecutors } from '@/utils/wordTools'

import { getBackendUrl } from './config'
import { toBackendName } from './toolNames'

export interface ToolManifestEntry {
  name: string
  description: string
  kind: 'client' | 'server'
  category: 'read' | 'select' | 'write' | 'server'
}

let cache: ToolManifestEntry[] | null = null

/**
 * Throws on drift in EITHER direction between the backend's declared
 * client-tool set and the local `wordToolExecutors` registry. This is the
 * guarantee that replaces a test suite: the two lists cannot silently
 * diverge, because loading the manifest fails loudly with the offending
 * names instead of silently executing (or silently omitting) a tool.
 */
function assertToolParity(manifest: ToolManifestEntry[]): void {
  const backendClient = new Set(manifest.filter(t => t.kind === 'client').map(t => t.name))
  const localNames = new Set(Object.keys(wordToolExecutors).map(toBackendName))

  const missingLocally = [...backendClient].filter(n => !localNames.has(n))
  const missingOnBackend = [...localNames].filter(n => !backendClient.has(n))
  if (missingLocally.length || missingOnBackend.length) {
    throw new Error(
      `Word tool registry mismatch. No local executor for: [${missingLocally}]. ` +
        `No backend definition for: [${missingOnBackend}].`,
    )
  }
}

export async function fetchToolManifest(): Promise<ToolManifestEntry[]> {
  if (cache) return cache
  const res = await fetch(`${getBackendUrl()}/api/tools`)
  if (!res.ok) throw new Error(`Failed to load tool manifest: ${res.status} ${await res.text()}`)
  const { tools } = await res.json()
  assertToolParity(tools)
  cache = tools
  return tools
}
