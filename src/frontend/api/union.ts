/**
 * Legacy thin shim — browser-mode (LangChain.js client-side) is deprecated.
 * All requests now route to the Python backend.
 *
 * Kept only to avoid touching the many call sites in HomePage.vue.
 */

import { streamAgentFromBackend, streamChatFromBackend, streamMultiAgentFromBackend } from '@/api/backend'

import { AgentOptions, MultiAgentOptions, ProviderOptions } from './types'

export async function getChatResponse(options: ProviderOptions, language?: string) {
  return streamChatFromBackend(options, language)
}

export async function getAgentResponse(options: AgentOptions, language?: string) {
  return streamAgentFromBackend(options, language)
}

export async function getMultiAgentResponse(options: MultiAgentOptions) {
  return streamMultiAgentFromBackend(options)
}
