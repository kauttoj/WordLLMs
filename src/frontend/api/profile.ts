/**
 * Profile-folder data persistence.
 *
 * The backend owns one folder on disk (the "profile") that holds
 * settings.json + prompts.json + mcp_servers.json + conversations.db.
 *
 * Frontend strategy: on app boot we GET /api/profile, then mirror its
 * settings + prompts into window.localStorage so existing components
 * keep reading via localStorage.getItem() unchanged. We patch
 * localStorage.setItem so any subsequent write to a profile-scoped
 * key is debounce-PUT to the backend, making the profile folder the
 * source of truth and localStorage a write-through cache.
 *
 * Switching profile reloads the page so every reactive component
 * re-initializes from the new profile's values.
 *
 * UI-only keys (panel sizes, current view, rendering prefs) bypass
 * the backend and stay on localStorage as before.
 */

import { ref } from 'vue'

import { getBackendUrl } from './backend'

// Keys that travel with the profile (settings.json)
const PROFILE_SETTING_KEYS = new Set<string>([
  // Common
  'api', 'localLanguage', 'replyLanguage', 'insertType',
  'useWordFormatting', 'useSelectedText', 'includeDocument',
  'agentMaxIterations', 'autoSwitchModeAfterCollaborative',
  'attachmentCharLimit', 'llmTimeout', 'tavilyApiKey',
  'defaultSystemPrompt', 'defaultPrompt',
  // OpenAI
  'openaiReasoningEffort', 'apiKey', 'model', 'customModel', 'customModels',
  'temperature', 'maxContextTokens', 'basePath',
  // Azure
  'azureReasoningEffort', 'azureAPIKey', 'azureAPIEndpoint',
  'azureDeploymentName', 'azureMaxContextTokens', 'azureTemperature',
  'azureAPIVersion', 'azureModel', 'azureCustomModels',
  // Gemini
  'geminiReasoningEffort', 'geminiAPIKey', 'geminiMaxContextTokens',
  'geminiTemperature', 'geminiModel', 'geminiCustomModel', 'geminiCustomModels',
  // Ollama
  'ollamaEndpoint', 'ollamaModel', 'ollamaTemperature',
  'ollamaCustomModel', 'ollamaCustomModels', 'ollamaMaxContextTokens',
  // Groq
  'groqAPIKey', 'groqTemperature', 'groqMaxContextTokens',
  'groqModel', 'groqCustomModel', 'groqCustomModels',
  // LMStudio
  'lmstudioEndpoint', 'lmstudioFilterThinking', 'lmstudioMaxContextTokens',
  'lmstudioTemperature', 'lmstudioModel', 'lmstudioCustomModel',
  'lmstudioCustomModels',
  // Anthropic
  'anthropicReasoningEffort', 'anthropicAPIKey', 'anthropicModel',
  'anthropicCustomModel', 'anthropicCustomModels', 'anthropicTemperature',
  'anthropicMaxContextTokens',
  // TogetherAI
  'togetheraiAPIKey', 'togetheraiTemperature', 'togetheraiMaxContextTokens',
  'togetheraiModel', 'togetheraiCustomModel', 'togetheraiCustomModels',
  // Tool prefs + MCP + multiagent + proxy
  'enabledWordTools', 'enabledGeneralTools', 'enabledMcpTools',
  'multiAgentConfig',
  'enableProxy', 'proxy',
])

// Keys stored as JSON-encoded strings in localStorage (arrays / objects).
// We parse/restringify so the profile JSON file stays human-readable.
const JSON_ENCODED_KEYS = new Set<string>([
  'customModels', 'anthropicCustomModels', 'azureCustomModels',
  'geminiCustomModels', 'ollamaCustomModels', 'groqCustomModels',
  'lmstudioCustomModels', 'togetheraiCustomModels',
  'enabledWordTools', 'enabledGeneralTools', 'enabledMcpTools',
  'multiAgentConfig', 'quickActionSlots', 'systemPromptPresets',
])

// Keys that live in prompts.json
const PROMPT_KEYS = new Set<string>([
  'quickActionSlots', 'systemPromptPresets', 'activeSystemPromptId',
])

// ---------------------------------------------------------------------------
// Reactive state
// ---------------------------------------------------------------------------

export const profilePath = ref<string>('')
export const profileHostPath = ref<string>('') // Host-side path when running in Docker
export const profileBrowseRoot = ref<string>('') // Container-side mount root, when restricted
export const profileLoaded = ref(false)
export const activeStreams = ref(0)
export const profileError = ref<string>('')

/** Translate a container-side path into the host-side equivalent for display. */
export function toHostPath(containerPath: string): string {
  if (!profileHostPath.value || !profileBrowseRoot.value) return containerPath
  const root = profileBrowseRoot.value
  if (containerPath === root) return profileHostPath.value
  if (!containerPath.startsWith(root + '/') && !containerPath.startsWith(root + '\\')) {
    return containerPath
  }
  const rel = containerPath.slice(root.length).replace(/^[/\\]+/, '')
  const sep = profileHostPath.value.includes('\\') ? '\\' : '/'
  return profileHostPath.value.replace(/[\/\\]+$/, '') + sep + rel.replace(/[\/\\]+/g, sep)
}

/** Translate a host-side path back to the container path before POSTing it. */
export function toContainerPath(input: string): string {
  if (!profileHostPath.value || !profileBrowseRoot.value) return input
  const host = profileHostPath.value.replace(/[\/\\]+$/, '')
  const root = profileBrowseRoot.value
  const lower = input.toLowerCase()
  const hostLower = host.toLowerCase()
  if (lower === hostLower) return root
  if (lower.startsWith(hostLower + '/') || lower.startsWith(hostLower + '\\')) {
    const rel = input.slice(host.length).replace(/^[/\\]+/, '')
    const sep = root.includes('\\') ? '\\' : '/'
    return root.replace(/[\/\\]+$/, '') + sep + rel.replace(/[\/\\]+/g, sep)
  }
  return input
}

// ---------------------------------------------------------------------------
// localStorage interception
// ---------------------------------------------------------------------------

const rawGetItem = window.localStorage.getItem.bind(window.localStorage)
const rawSetItem = window.localStorage.setItem.bind(window.localStorage)
const rawRemoveItem = window.localStorage.removeItem.bind(window.localStorage)

function encodeForBackend(key: string, lsValue: string): unknown {
  if (!JSON_ENCODED_KEYS.has(key)) return lsValue
  try { return JSON.parse(lsValue) } catch { return lsValue }
}

function decodeForLocalStorage(key: string, backendValue: unknown): string {
  if (JSON_ENCODED_KEYS.has(key)) return JSON.stringify(backendValue)
  return typeof backendValue === 'string' ? backendValue : JSON.stringify(backendValue)
}

let settingsTimer: number | null = null
let promptsTimer: number | null = null

function collectPayload(keys: Set<string>): Record<string, unknown> {
  const payload: Record<string, unknown> = {}
  for (const key of keys) {
    const v = rawGetItem(key)
    if (v !== null) payload[key] = encodeForBackend(key, v)
  }
  return payload
}

async function putJson(endpoint: string, payload: unknown): Promise<void> {
  const res = await fetch(`${getBackendUrl()}${endpoint}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${endpoint} ${res.status}: ${text.substring(0, 200)}`)
  }
}

function scheduleSaveSettings() {
  if (settingsTimer) clearTimeout(settingsTimer)
  settingsTimer = window.setTimeout(() => {
    putJson('/api/profile/settings', collectPayload(PROFILE_SETTING_KEYS))
      .catch(err => console.error('[Profile] settings save failed:', err))
  }, 600)
}

function scheduleSavePrompts() {
  if (promptsTimer) clearTimeout(promptsTimer)
  promptsTimer = window.setTimeout(() => {
    putJson('/api/profile/prompts', collectPayload(PROMPT_KEYS))
      .catch(err => console.error('[Profile] prompts save failed:', err))
  }, 600)
}

function patchLocalStorage() {
  window.localStorage.setItem = (key: string, value: string) => {
    rawSetItem(key, value)
    if (PROFILE_SETTING_KEYS.has(key)) scheduleSaveSettings()
    else if (PROMPT_KEYS.has(key)) scheduleSavePrompts()
  }
  window.localStorage.removeItem = (key: string) => {
    rawRemoveItem(key)
    if (PROFILE_SETTING_KEYS.has(key)) scheduleSaveSettings()
    else if (PROMPT_KEYS.has(key)) scheduleSavePrompts()
  }
}

// ---------------------------------------------------------------------------
// Hydration
// ---------------------------------------------------------------------------

function hydrateFromSnapshot(snapshot: ProfileSnapshot) {
  // Wipe any stale profile-scoped keys, then write fresh values.
  // UI keys (chatMode, panel sizes, etc.) are untouched.
  for (const key of [...PROFILE_SETTING_KEYS, ...PROMPT_KEYS]) {
    rawRemoveItem(key)
  }
  for (const [key, value] of Object.entries(snapshot.settings)) {
    if (PROFILE_SETTING_KEYS.has(key)) {
      rawSetItem(key, decodeForLocalStorage(key, value))
    }
  }
  for (const [key, value] of Object.entries(snapshot.prompts)) {
    if (PROMPT_KEYS.has(key)) {
      rawSetItem(key, decodeForLocalStorage(key, value))
    }
  }
  profilePath.value = snapshot.path
  profileHostPath.value = snapshot.host_path ?? ''
  profileBrowseRoot.value = snapshot.browse_root ?? ''
  activeStreams.value = snapshot.active_streams
}

// ---------------------------------------------------------------------------
// HTTP client
// ---------------------------------------------------------------------------

export interface ProfileSnapshot {
  path: string
  host_path: string | null
  browse_root: string | null
  settings: Record<string, unknown>
  prompts: Record<string, unknown>
  active_streams: number
}

export async function fetchProfile(): Promise<ProfileSnapshot> {
  const res = await fetch(`${getBackendUrl()}/api/profile`)
  if (!res.ok) throw new Error(`GET /api/profile ${res.status}`)
  return res.json()
}

export async function switchProfile(newPath: string): Promise<void> {
  const res = await fetch(`${getBackendUrl()}/api/profile/path`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: newPath }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: `${res.status}` }))
    throw new Error(data.detail || `Switch failed: ${res.status}`)
  }
  // Clear thread pointer — it referenced the OLD profile's DB.
  rawRemoveItem('threadId')
  // Reload so every Vue component reinitializes from the new localStorage.
  window.location.reload()
}

export async function browseProfileDir(path: string): Promise<{
  current_path: string
  parent_path: string | null
  entries: { name: string; path: string; is_dir: boolean }[]
}> {
  const url = new URL(`${getBackendUrl() || window.location.origin}/api/profile/browse-dir`)
  if (path) url.searchParams.set('path', path)
  const res = await fetch(url.toString())
  if (!res.ok) throw new Error(`Browse failed: ${res.status}`)
  return res.json()
}

// ---------------------------------------------------------------------------
// Active-stream polling — drives "switch profile disabled" UI.
// ---------------------------------------------------------------------------

let pollTimer: number | null = null

export function startStreamCountPoll(intervalMs = 2000) {
  if (pollTimer) return
  pollTimer = window.setInterval(async () => {
    try {
      const snap = await fetchProfile()
      activeStreams.value = snap.active_streams
      profileHostPath.value = snap.host_path ?? ''
    } catch {
      // Backend hiccup; leave previous value.
    }
  }, intervalMs)
}

// ---------------------------------------------------------------------------
// Bootstrap — call once before mounting the app.
// ---------------------------------------------------------------------------

export async function bootstrapProfile(): Promise<void> {
  const snapshot = await fetchProfile()
  hydrateFromSnapshot(snapshot)
  patchLocalStorage()
  profileLoaded.value = true
}
