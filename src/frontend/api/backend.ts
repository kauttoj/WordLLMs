/**
 * HTTP client for Python backend API calls.
 * Replaces direct LangChain usage with backend API calls.
 *
 * Server-side tools (web_search, calculate, etc.) execute in Python.
 * Client-side Word tools use an RPC pattern: the backend pauses when
 * the LLM calls a Word tool, sends a `client_tool_call` SSE event,
 * and the frontend executes the Office.js code then calls
 * /api/agent/continue with the results.
 */

import { getWordTool, WordToolName } from '@/utils/wordTools'

import { AgentOptions, MultiAgentExpertConfig, MultiAgentOptions, ProviderOptions } from './types'

// Backend URL - empty string means same origin (relative paths)
// Set to 'http://localhost:8000' for development with separate servers
const DEFAULT_BACKEND_URL = ''

export function getBackendUrl(): string {
  return localStorage.getItem('backendUrl') ?? DEFAULT_BACKEND_URL
}

export function setBackendUrl(url: string): void {
  localStorage.setItem('backendUrl', url)
}

interface BackendMessage {
  role: 'system' | 'user' | 'assistant'
  content: string
}

interface BackendCredentials {
  api_key?: string
  base_url?: string
  endpoint?: string
  api_version?: string
  deployment_name?: string
}

interface FileAttachment {
  filename: string
  data: string // base64
}

interface ChatRequestBody {
  messages: BackendMessage[]
  provider: string
  model: string
  credentials: BackendCredentials
  temperature: number
  max_context_tokens: number
  llm_timeout: number
  filter_thinking?: boolean
  language?: string
  additional_system_prompt?: string
  conversation_id?: string
  attachments?: FileAttachment[]
  attachment_char_limit?: number
}

interface AgentRequestBody extends ChatRequestBody {
  tools: string[]
  thread_id?: string
  conversation_id?: string
  recursion_limit: number
  tavily_api_key?: string
}

interface AgentContinueRequestBody {
  session_id: string
  tool_results: { call_id: string; name: string; result: string }[]
  provider: string
  model: string
  credentials: BackendCredentials
  temperature: number
  max_context_tokens: number
  llm_timeout: number
  filter_thinking?: boolean
  recursion_limit: number
  tavily_api_key?: string
  tools: string[]
}

interface ClientToolCall {
  call_id: string
  name: string
  args: any
}

function convertMessages(messages: any[]): BackendMessage[] {
  return messages.map(msg => {
    // Handle LangChain message objects
    if (typeof msg._getType === 'function') {
      const type = msg._getType()
      return {
        role: type === 'human' ? 'user' : type === 'ai' ? 'assistant' : 'system',
        content: typeof msg.content === 'string' ? msg.content : '',
      }
    }
    // Handle plain objects
    return {
      role: msg.role || 'user',
      content: msg.content || '',
    }
  })
}

function buildCredentials(options: ProviderOptions | AgentOptions): BackendCredentials {
  const creds: BackendCredentials = {}

  if (options.provider === 'official' && 'config' in options && options.config) {
    creds.api_key = options.config.apiKey
    if (options.config.baseURL) {
      creds.base_url = options.config.baseURL
    }
  } else if (options.provider === 'azure') {
    const opts = options as any
    creds.api_key = opts.azureAPIKey
    creds.endpoint = opts.azureAPIEndpoint
    creds.api_version = opts.azureAPIVersion
    creds.deployment_name = opts.azureDeploymentName
  } else if (options.provider === 'gemini') {
    const opts = options as any
    creds.api_key = opts.geminiAPIKey
  } else if (options.provider === 'groq') {
    const opts = options as any
    creds.api_key = opts.groqAPIKey
  } else if (options.provider === 'ollama') {
    const opts = options as any
    creds.base_url = opts.ollamaEndpoint
  } else if (options.provider === 'lmstudio') {
    const opts = options as any
    creds.base_url = opts.lmstudioEndpoint
  } else if (options.provider === 'anthropic') {
    const opts = options as any
    creds.api_key = opts.anthropicAPIKey
  }

  return creds
}

function getModelName(options: ProviderOptions | AgentOptions): string {
  if (options.provider === 'lmstudio') {
    if ('lmstudioModel' in options && options.lmstudioModel) return options.lmstudioModel
    return 'default'
  }
  if ('model' in options && options.model) return options.model
  if ('anthropicModel' in options && options.anthropicModel) return options.anthropicModel
  if ('ollamaModel' in options && options.ollamaModel) return options.ollamaModel
  if ('groqModel' in options && options.groqModel) return options.groqModel
  if ('geminiModel' in options && options.geminiModel) return options.geminiModel
  if ('azureDeploymentName' in options && options.azureDeploymentName) return options.azureDeploymentName
  throw new Error(`No model configured for provider "${options.provider}". Select a model in Settings.`)
}

function mapProvider(provider: string): string {
  // Map frontend provider names to backend names
  if (provider === 'official') return 'openai'
  return provider
}

// ---------------------------------------------------------------------------
// Tool name mapping (frontend camelCase ↔ backend snake_case)
// ---------------------------------------------------------------------------

/** Map frontend tool names to backend Python tool names. */
function mapToolName(frontendName: string): string | null {
  const mapping: Record<string, string> = {
    // Server-side tools (execute natively in Python)
    webSearch: 'web_search',
    fetchWebContent: 'fetch_url',
    getCurrentDate: 'get_current_date',
    calculateMath: 'calculate',
    // Client-side Word tools (schema only on backend, executed here via Office.js)
    getSelectedText: 'get_selected_text',
    getDocumentContent: 'get_document_content',
    insertText: 'insert_text',
    replaceSelectedText: 'replace_selected_text',
    appendText: 'append_text',
    insertParagraph: 'insert_paragraph',
    formatText: 'format_text',
    searchAndReplace: 'search_and_replace',
    searchAndReplaceInSelection: 'search_and_replace_in_selection',
    getDocumentProperties: 'get_document_properties',
    insertTable: 'insert_table',
    insertList: 'insert_list',
    deleteText: 'delete_text',
    clearFormatting: 'clear_formatting',
    setParagraphFormat: 'set_paragraph_format',
    setStyle: 'set_style',
    insertPageBreak: 'insert_page_break',
    getRangeInfo: 'get_range_info',
    selectText: 'select_text',
    insertImage: 'insert_image',
    getTableInfo: 'get_table_info',
    insertBookmark: 'insert_bookmark',
    goToBookmark: 'go_to_bookmark',
    insertContentControl: 'insert_content_control',
    findText: 'find_text',
    findAndSelectText: 'find_and_select_text',
    selectBetweenText: 'select_between_text',
  }
  return mapping[frontendName] ?? null
}

/** Reverse mapping: backend snake_case → frontend camelCase. */
const BACKEND_TO_FRONTEND_TOOL: Record<string, string> = {
  get_selected_text: 'getSelectedText',
  get_document_content: 'getDocumentContent',
  insert_text: 'insertText',
  replace_selected_text: 'replaceSelectedText',
  append_text: 'appendText',
  insert_paragraph: 'insertParagraph',
  format_text: 'formatText',
  search_and_replace: 'searchAndReplace',
  search_and_replace_in_selection: 'searchAndReplaceInSelection',
  get_document_properties: 'getDocumentProperties',
  insert_table: 'insertTable',
  insert_list: 'insertList',
  delete_text: 'deleteText',
  clear_formatting: 'clearFormatting',
  set_paragraph_format: 'setParagraphFormat',
  set_style: 'setStyle',
  insert_page_break: 'insertPageBreak',
  get_range_info: 'getRangeInfo',
  select_text: 'selectText',
  insert_image: 'insertImage',
  get_table_info: 'getTableInfo',
  insert_bookmark: 'insertBookmark',
  go_to_bookmark: 'goToBookmark',
  insert_content_control: 'insertContentControl',
  find_text: 'findText',
  find_and_select_text: 'findAndSelectText',
  select_between_text: 'selectBetweenText',
}

// ---------------------------------------------------------------------------
// SSE stream parser
// ---------------------------------------------------------------------------

interface ParseSSEOptions {
  onText: (content: string, speaker?: string) => void
  onMessage?: (content: string, speaker?: string, round?: number) => void
  onToolCall?: (name: string, args: any, speaker?: string) => void
  onToolResult?: (name: string, result: string, speaker?: string) => void
  onClientToolCall?: (sessionId: string, toolCalls: ClientToolCall[]) => void
  onError?: (error: string) => void
  onNewBlock?: (speaker?: string) => void
  onOverseerDecision?: (decision: string) => void
  abortSignal?: AbortSignal
}

async function parseSSEStream(response: Response, options: ParseSSEOptions): Promise<void> {
  const reader = response.body?.getReader()
  if (!reader) throw new Error('No response body')

  const decoder = new TextDecoder()
  let buffer = ''
  let fullContent = ''
  let currentSpeaker = ''
  let inThinkingBlock = false
  let currentEvent = ''
  let currentData = ''

  try {
    while (true) {
      if (options.abortSignal?.aborted) break

      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // Parse SSE events
      const lines = buffer.split('\n')
      buffer = lines.pop() || '' // Keep incomplete line in buffer

      for (const line of lines) {
        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          currentData = line.slice(5).trim()
        } else if (line.trim() === '' && currentEvent && currentData) {
          // End of event, process it
          try {
            const data = JSON.parse(currentData)

            console.log('[Backend SSE]', {
              event: currentEvent,
              dataLength: currentData.length,
              dataPreview: currentData.substring(0, 100),
            })

            switch (currentEvent) {
              case 'thinking':
                if (data.content) {
                  // Reset content when speaker changes (multiagent)
                  if (data.speaker && data.speaker !== currentSpeaker) {
                    fullContent = ''
                    inThinkingBlock = false
                    currentSpeaker = data.speaker
                  }
                  if (!inThinkingBlock) {
                    fullContent += '<think>'
                    inThinkingBlock = true
                  }
                  fullContent += data.content
                  options.onText(fullContent, data.speaker)
                }
                break
              case 'text':
                if (data.content) {
                  // Reset content when speaker changes (multiagent)
                  if (data.speaker && data.speaker !== currentSpeaker) {
                    fullContent = ''
                    inThinkingBlock = false
                    currentSpeaker = data.speaker
                  }
                  if (inThinkingBlock) {
                    fullContent += '</think>'
                    inThinkingBlock = false
                  }
                  fullContent += data.content
                  console.log('[Backend] Content update:', {
                    contentLength: fullContent.length,
                    contentPreview: fullContent.substring(0, 50),
                    speaker: data.speaker,
                  })
                  console.log('[Backend] Calling onText with', fullContent.length, 'chars, speaker:', data.speaker)
                  options.onText(fullContent, data.speaker)
                }
                break
              case 'tool_call':
                fullContent = ''
                if (options.onToolCall) {
                  options.onToolCall(data.name, data.args, data.speaker)
                }
                break
              case 'tool_result':
                if (options.onToolResult) {
                  options.onToolResult(data.name, data.result, data.speaker)
                }
                break
              case 'client_tool_call':
                fullContent = ''
                if (options.onClientToolCall) {
                  options.onClientToolCall(data.session_id, data.tool_calls)
                }
                break
              case 'message':
                // Complete message event (multiagent mode) — NOT accumulated into fullContent
                if (data.content && options.onMessage) {
                  options.onMessage(data.content, data.speaker, data.round)
                }
                break
              case 'overseer_decision':
                if (options.onOverseerDecision) {
                  options.onOverseerDecision(data.decision)
                }
                break
              case 'new_block':
                fullContent = ''
                inThinkingBlock = false
                if (options.onNewBlock) {
                  options.onNewBlock(data.speaker)
                }
                break
              case 'error':
                if (options.onError) {
                  options.onError(data.error)
                }
                break
              case 'done':
                // Close any open thinking block before stream ends
                if (inThinkingBlock) {
                  fullContent += '</think>'
                  inThinkingBlock = false
                  options.onText(fullContent, data.speaker)
                }
                break
            }
          } catch (parseError) {
            const errorMsg = `Failed to parse SSE event. Data: ${currentData.substring(0, 100)}`
            console.error('[Backend] SSE Parse Error:', parseError, 'Data:', currentData)
            if (options.onError) {
              options.onError(errorMsg)
            }
            // Don't continue processing - this is a fatal error
            break
          }

          currentEvent = ''
          currentData = ''
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

// ---------------------------------------------------------------------------
// Chat streaming (no tools)
// ---------------------------------------------------------------------------

export async function streamChatFromBackend(options: ProviderOptions, language?: string): Promise<void> {
  const backendUrl = getBackendUrl()

  const body: ChatRequestBody = {
    messages: convertMessages(options.messages),
    provider: mapProvider(options.provider),
    model: getModelName(options),
    credentials: buildCredentials(options),
    temperature: options.temperature ?? 1.0,
    max_context_tokens: options.maxContextTokens ?? 128000,
    llm_timeout: options.llmTimeout ?? 60,
    filter_thinking: 'lmstudioFilterThinking' in options ? (options.lmstudioFilterThinking ?? true) : false,
  }

  // Add language if provided (signals backend to generate default prompt)
  if (language) {
    body.language = language
  }

  // Add additional system prompt (persistent behavioral instructions)
  if (options.additionalSystemPrompt) {
    body.additional_system_prompt = options.additionalSystemPrompt
  }

  // Add conversation_id for cross-mode consigliere history
  if (options.conversationId) {
    body.conversation_id = options.conversationId
  }

  if (options.attachments?.length) {
    body.attachments = options.attachments
    body.attachment_char_limit = options.attachmentCharLimit ?? 50000
  }

  try {
    console.log('[Backend] Starting chat request:', {
      provider: body.provider,
      model: body.model,
      messageCount: body.messages.length,
    })

    const response = await fetch(`${backendUrl}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: options.abortSignal,
    })

    console.log('[Backend] Response received:', {
      ok: response.ok,
      status: response.status,
      contentType: response.headers.get('content-type'),
    })

    if (!response.ok) {
      const errorText = await response.text()
      console.error('[Backend] HTTP Error:', response.status, errorText)
      throw new Error(`Backend returned ${response.status}: ${errorText.substring(0, 200)}`)
    }

    await parseSSEStream(response, {
      onText: options.onStream,
      onError: error => {
        options.errorIssue.value = error
      },
      abortSignal: options.abortSignal,
    })
  } catch (error: any) {
    if (error.name === 'AbortError' || options.abortSignal?.aborted) {
      throw error
    }
    options.errorIssue.value = error.message || 'Network request failed'
    console.error('[Backend] Chat error:', error)
  } finally {
    options.loading.value = false
  }
}

// ---------------------------------------------------------------------------
// Agent streaming with client-side Word tool execution loop
// ---------------------------------------------------------------------------

/**
 * Execute a single client-side Word tool via Office.js.
 * Returns the string result (or error message).
 */
async function executeClientTool(tc: ClientToolCall): Promise<string> {
  const frontendName = BACKEND_TO_FRONTEND_TOOL[tc.name]
  if (!frontendName) {
    throw new Error(`No frontend mapping for backend tool: ${tc.name}`)
  }

  const toolDef = getWordTool(frontendName as WordToolName)
  if (!toolDef) {
    throw new Error(`Word tool not found: ${frontendName}`)
  }

  const result = await toolDef.execute(tc.args)
  return String(result)
}

export async function streamAgentFromBackend(options: AgentOptions, language?: string): Promise<void> {
  const backendUrl = getBackendUrl()

  // Extract and map tool names from tool objects
  const toolNames: string[] = []
  if (options.tools) {
    for (const tool of options.tools) {
      if (typeof tool.name === 'string') {
        const backendName = mapToolName(tool.name)
        if (backendName) toolNames.push(backendName)
      }
    }
  }

  // Build the initial agent request
  const agentBody: AgentRequestBody = {
    messages: convertMessages(options.messages),
    provider: mapProvider(options.provider),
    model: getModelName(options),
    credentials: buildCredentials(options),
    temperature: options.temperature ?? 1.0,
    max_context_tokens: options.maxContextTokens ?? 128000,
    llm_timeout: options.llmTimeout ?? 60,
    filter_thinking: options.lmstudioFilterThinking ?? false,
    tools: toolNames,
    thread_id: options.threadId,
    conversation_id: options.conversationId,
    recursion_limit: options.recursionLimit ?? 25,
    tavily_api_key: localStorage.getItem('tavilyApiKey') || undefined,
  }

  // Add language if provided (signals backend to generate default prompt)
  if (language) {
    agentBody.language = language
  }

  // Add additional system prompt (persistent behavioral instructions)
  if (options.additionalSystemPrompt) {
    agentBody.additional_system_prompt = options.additionalSystemPrompt
  }

  if (options.attachments?.length) {
    agentBody.attachments = options.attachments
    agentBody.attachment_char_limit = options.attachmentCharLimit ?? 50000
  }

  // RPC loop: stream → if client_tool_call → execute Office.js → continue → repeat
  let requestUrl = `${backendUrl}/api/agent`
  let requestBody: AgentRequestBody | AgentContinueRequestBody = agentBody

  try {
    while (true) {
      if (options.abortSignal?.aborted) break

      console.log('[Backend] Starting agent request:', {
        url: requestUrl,
        provider: agentBody.provider,
        model: agentBody.model,
      })

      const response = await fetch(requestUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
        signal: options.abortSignal,
      })

      if (!response.ok) {
        const errorText = await response.text()
        console.error('[Backend] HTTP Error:', response.status, errorText)
        throw new Error(`Backend returned ${response.status}: ${errorText.substring(0, 200)}`)
      }

      // Parse SSE stream, collecting any client tool calls
      let pendingClientCalls: ClientToolCall[] | null = null
      let sessionId: string | null = null

      await parseSSEStream(response, {
        onText: options.onStream,
        onToolCall: options.onToolCall,
        onToolResult: options.onToolResult,
        onNewBlock: options.onNewBlock,
        onClientToolCall: (sid, toolCalls) => {
          sessionId = sid
          pendingClientCalls = toolCalls
        },
        onError: error => {
          if (error.includes('recursion') || error.includes('RecursionError')) {
            options.errorIssue.value = 'recursionLimitExceeded'
          } else {
            options.errorIssue.value = error
          }
        },
        abortSignal: options.abortSignal,
      })

      // If no client tool calls are pending, the agent is done
      if (!pendingClientCalls || !sessionId) break

      // Execute each pending client tool via Office.js
      console.log('[Backend] Executing', pendingClientCalls.length, 'client-side Word tool(s)')
      const toolResults: { call_id: string; name: string; result: string }[] = []

      for (const tc of pendingClientCalls) {
        console.log('[Backend] Executing client tool:', tc.name, tc.args)
        try {
          const result = await executeClientTool(tc)
          if (options.onToolResult) {
            options.onToolResult(tc.name, result)
          }
          toolResults.push({ call_id: tc.call_id, name: tc.name, result })
        } catch (err: any) {
          const errMsg = `Error: ${err.message || 'Unknown error'}`
          console.error('[Backend] Client tool error:', tc.name, err)
          if (options.onToolResult) {
            options.onToolResult(tc.name, errMsg)
          }
          toolResults.push({ call_id: tc.call_id, name: tc.name, result: errMsg })
        }
      }

      // Continue the agent loop with tool results
      requestUrl = `${backendUrl}/api/agent/continue`
      requestBody = {
        session_id: sessionId,
        tool_results: toolResults,
        provider: agentBody.provider,
        model: agentBody.model,
        credentials: agentBody.credentials,
        temperature: agentBody.temperature,
        max_context_tokens: agentBody.max_context_tokens,
        llm_timeout: agentBody.llm_timeout,
        filter_thinking: agentBody.filter_thinking,
        recursion_limit: agentBody.recursion_limit,
        tavily_api_key: agentBody.tavily_api_key,
        tools: agentBody.tools,
      }
    }
  } catch (error: any) {
    if (error.name === 'AbortError' || options.abortSignal?.aborted) {
      throw error
    }
    options.errorIssue.value = error.message || 'Network request failed'
    console.error('[Backend] Agent error:', error)
  } finally {
    options.loading.value = false
  }
}

export async function checkBackendHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${getBackendUrl()}/api/health`, {
      method: 'GET',
      signal: AbortSignal.timeout(5000),
    })
    return response.ok
  } catch {
    return false
  }
}

export async function fetchContextStats(conversationId: string): Promise<{ chars: number; tokens: number }> {
  const resp = await fetch(`${getBackendUrl()}/api/context-stats/${conversationId}`)
  if (!resp.ok) throw new Error(`Context stats failed: ${resp.status}`)
  return resp.json()
}

// ---------------------------------------------------------------------------
// MultiAgent streaming with client-side Word tool execution loop
// ---------------------------------------------------------------------------

function buildExpertConfig(expert: MultiAgentExpertConfig): any {
  const creds: BackendCredentials = {}

  if (expert.provider === 'official' && expert.config) {
    creds.api_key = expert.config.apiKey
    if (expert.config.baseURL) {
      creds.base_url = expert.config.baseURL
    }
  } else if (expert.provider === 'azure') {
    creds.api_key = expert.azureAPIKey
    creds.endpoint = expert.azureAPIEndpoint
    creds.api_version = expert.azureAPIVersion
    creds.deployment_name = expert.azureDeploymentName
  } else if (expert.provider === 'gemini') {
    creds.api_key = expert.geminiAPIKey
  } else if (expert.provider === 'groq') {
    creds.api_key = expert.groqAPIKey
  } else if (expert.provider === 'ollama') {
    creds.base_url = expert.ollamaEndpoint
  } else if (expert.provider === 'lmstudio') {
    creds.base_url = expert.lmstudioEndpoint
  } else if (expert.provider === 'anthropic') {
    creds.api_key = expert.anthropicAPIKey
  }

  let model: string | undefined
  if (expert.provider === 'lmstudio') {
    model = expert.lmstudioModel || 'default'
  } else if (expert.model) {
    model = expert.model
  } else if (expert.ollamaModel) {
    model = expert.ollamaModel
  } else if (expert.groqModel) {
    model = expert.groqModel
  } else if (expert.geminiModel) {
    model = expert.geminiModel
  } else if (expert.azureDeploymentName) {
    model = expert.azureDeploymentName
  } else if (expert.anthropicModel) {
    model = expert.anthropicModel
  }

  if (!model) {
    throw new Error(`No model configured for provider "${expert.provider}". Select a model in Settings.`)
  }

  return {
    provider: mapProvider(expert.provider),
    model,
    credentials: creds,
    temperature: expert.temperature ?? 1.0,
    max_context_tokens: expert.maxContextTokens ?? 128000,
  }
}

interface MultiAgentRequestBody {
  messages: BackendMessage[]
  mode: 'parallel' | 'collaborative'
  operating_mode?: 'combined' | 'legacy'
  max_rounds: number
  use_expert_memory: boolean
  expert_full_history?: boolean
  use_expert_parallelization?: boolean
  conversation_id?: string
  experts: any[]
  overseer: any
  synthesizer?: any
  formatter?: any
  expert_tools: string[]
  supervisor_tools: string[]
  recursion_limit: number
  llm_timeout: number
  filter_thinking: boolean
  language?: string
  additional_system_prompt?: string
  attachments?: FileAttachment[]
  attachment_char_limit?: number
  tavily_api_key?: string
}

interface MultiAgentContinueRequestBody {
  session_id: string
  tool_results: { call_id: string; name: string; result: string }[]
}

// Build tool lists for multiagent, filtered by user-enabled tools
function buildMultiAgentToolLists(
  enabledWordToolNames: string[],
  enabledGeneralToolNames: string[],
): { expertTools: string[]; supervisorTools: string[] } {
  // Map enabled frontend names to backend names
  const enabledBackend = new Set(
    [...enabledWordToolNames, ...enabledGeneralToolNames]
      .map(name => mapToolName(name))
      .filter((n): n is string => n !== null),
  )

  const isEnabled = (name: string) => enabledBackend.has(name)

  // READ_ONLY Word tools for experts (backend snake_case names)
  // Must match READ_ONLY_WORD_TOOLS in src/utils/wordTools.ts
  const readOnlyWordTools = [
    'get_selected_text',
    'get_document_content',
    'get_document_properties',
    'get_range_info',
    'get_table_info',
    'find_text',
    'select_text',
    'find_and_select_text',
    'select_between_text',
    'go_to_bookmark',
  ].filter(isEnabled)

  // Write Word tools for supervisors
  const writeWordTools = [
    'insert_text',
    'replace_selected_text',
    'append_text',
    'insert_paragraph',
    'format_text',
    'search_and_replace',
    'search_and_replace_in_selection',
    'insert_table',
    'insert_list',
    'delete_text',
    'clear_formatting',
    'set_paragraph_format',
    'set_style',
    'insert_page_break',
    'insert_image',
    'insert_bookmark',
    'insert_content_control',
  ].filter(isEnabled)

  // General tools (backend tool names)
  const generalTools = ['web_search', 'fetch_url', 'calculate', 'get_current_date'].filter(isEnabled)

  return {
    expertTools: [...readOnlyWordTools, ...generalTools],
    supervisorTools: [...readOnlyWordTools, ...writeWordTools, ...generalTools],
  }
}

export async function streamMultiAgentFromBackend(options: MultiAgentOptions): Promise<void> {
  const backendUrl = getBackendUrl()

  // Build expert configurations
  const expertConfigs = options.experts.map(buildExpertConfig)
  const overseerConfig = buildExpertConfig(options.overseer)
  const synthesizerConfig = options.synthesizer ? buildExpertConfig(options.synthesizer) : null
  const formatterConfig = options.formatter ? buildExpertConfig(options.formatter) : undefined

  // Build tool lists filtered by user's enabled tools
  const { expertTools, supervisorTools } = buildMultiAgentToolLists(
    options.enabledWordTools ?? [],
    options.enabledGeneralTools ?? [],
  )

  // Build the initial multiagent request
  const multiAgentBody: MultiAgentRequestBody = {
    messages: convertMessages(options.messages),
    mode: options.mode,
    operating_mode: options.operatingMode ?? 'legacy',
    max_rounds: options.maxRounds ?? 3,
    use_expert_memory: options.useExpertMemory ?? true,
    expert_full_history: options.expertFullHistory ?? false,
    use_expert_parallelization: options.useExpertParallelization ?? true,
    experts: expertConfigs,
    overseer: overseerConfig,
    synthesizer: synthesizerConfig,
    formatter: formatterConfig,
    expert_tools: expertTools,
    supervisor_tools: supervisorTools,
    recursion_limit: options.recursionLimit ?? 25,
    llm_timeout: options.llmTimeout ?? 60,
    filter_thinking: false, // Can be enhanced to support per-expert thinking filtering
    language: options.language,
    conversation_id: options.conversationId,
    tavily_api_key: localStorage.getItem('tavilyApiKey') || undefined,
  }

  // Add additional system prompt (persistent behavioral instructions)
  if (options.additionalSystemPrompt) {
    multiAgentBody.additional_system_prompt = options.additionalSystemPrompt
  }

  if (options.attachments?.length) {
    multiAgentBody.attachments = options.attachments
    multiAgentBody.attachment_char_limit = options.attachmentCharLimit ?? 50000
  }

  // RPC loop: stream → if client_tool_call → execute Office.js → continue → repeat
  let requestUrl = `${backendUrl}/api/multiagent`
  let requestBody: MultiAgentRequestBody | MultiAgentContinueRequestBody = multiAgentBody

  try {
    while (true) {
      if (options.abortSignal?.aborted) break

      console.log('[Backend] Starting multiagent request:', {
        url: requestUrl,
        mode: multiAgentBody.mode,
        expertCount: expertConfigs.length,
      })

      const response = await fetch(requestUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
        signal: options.abortSignal,
      })

      if (!response.ok) {
        const errorText = await response.text()
        console.error('[Backend] HTTP Error:', response.status, errorText)
        throw new Error(`Backend returned ${response.status}: ${errorText.substring(0, 200)}`)
      }

      // Parse SSE stream, collecting any client tool calls
      let pendingClientCalls: ClientToolCall[] | null = null
      let sessionId: string | null = null

      await parseSSEStream(response, {
        onText: (fullContent: string, speaker?: string) => {
          console.error('[MultiAgent] Unexpected text event received - multiagent should only emit message events')
          options.onStream(fullContent, speaker)
        },
        onMessage: (content: string, speaker?: string, round?: number) => {
          options.onMessage?.(content, speaker, round)
        },
        onToolCall: (name: string, args: any, speaker?: string) => {
          if (options.onToolCall) options.onToolCall(name, args, speaker)
        },
        onToolResult: (name: string, result: string, speaker?: string) => {
          if (options.onToolResult) options.onToolResult(name, result, speaker)
        },
        onClientToolCall: (sid, toolCalls) => {
          sessionId = sid
          pendingClientCalls = toolCalls
        },
        onOverseerDecision: (decision: string) => {
          options.onOverseerDecision?.(decision)
        },
        onError: error => {
          if (error.includes('recursion') || error.includes('RecursionError')) {
            options.errorIssue.value = 'recursionLimitExceeded'
          } else {
            options.errorIssue.value = error
          }
        },
        abortSignal: options.abortSignal,
      })

      // If no client tool calls are pending, the multiagent is done
      if (!pendingClientCalls || !sessionId) break

      // Execute each pending client tool via Office.js
      console.log('[Backend] Executing', pendingClientCalls.length, 'client-side Word tool(s)')
      const toolResults: { call_id: string; name: string; result: string }[] = []

      for (const tc of pendingClientCalls) {
        console.log('[Backend] Executing client tool:', tc.name, tc.args)
        try {
          const result = await executeClientTool(tc)
          if (options.onToolResult) {
            options.onToolResult(tc.name, result)
          }
          toolResults.push({ call_id: tc.call_id, name: tc.name, result })
        } catch (err: any) {
          const errMsg = `Error: ${err.message || 'Unknown error'}`
          console.error('[Backend] Client tool error:', tc.name, err)
          if (options.onToolResult) {
            options.onToolResult(tc.name, errMsg)
          }
          toolResults.push({ call_id: tc.call_id, name: tc.name, result: errMsg })
        }
      }

      // Continue the multiagent loop with tool results
      requestUrl = `${backendUrl}/api/multiagent/continue`
      requestBody = {
        session_id: sessionId,
        tool_results: toolResults,
      }
    }
  } catch (error: any) {
    if (error.name === 'AbortError' || options.abortSignal?.aborted) {
      throw error
    }
    options.errorIssue.value = error.message || 'Network request failed'
    console.error('[Backend] MultiAgent error:', error)
  } finally {
    options.loading.value = false
  }
}

// ---------------------------------------------------------------------------
// Thread CRUD (GUI display history, stored in backend SQLite)
// ---------------------------------------------------------------------------

export interface BackendThread {
  id: string
  title: string
  messages: any[]
  mode: string
  provider: string
  model: string
  messageCount: number
  createdAt: string
  updatedAt: string
}

export async function fetchThreadList(limit: number = 50): Promise<BackendThread[]> {
  const backendUrl = getBackendUrl()
  const response = await fetch(`${backendUrl}/api/threads?limit=${limit}`)
  if (!response.ok) {
    throw new Error(`Failed to list threads: ${response.status}`)
  }
  const data = await response.json()
  return data.threads ?? []
}

export async function fetchThread(threadId: string): Promise<BackendThread | null> {
  const backendUrl = getBackendUrl()
  const response = await fetch(`${backendUrl}/api/threads/${encodeURIComponent(threadId)}`)
  if (!response.ok) {
    throw new Error(`Failed to get thread: ${response.status}`)
  }
  const data = await response.json()
  return data.thread ?? null
}

export async function saveThreadToBackend(thread: BackendThread): Promise<void> {
  const backendUrl = getBackendUrl()
  const response = await fetch(`${backendUrl}/api/threads`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(thread),
  })
  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(`Failed to save thread: ${response.status} ${errorText.substring(0, 200)}`)
  }
}

export async function deleteThreadFromBackend(threadId: string): Promise<boolean> {
  const backendUrl = getBackendUrl()
  const response = await fetch(`${backendUrl}/api/threads/${encodeURIComponent(threadId)}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new Error(`Failed to delete thread: ${response.status}`)
  }
  const data = await response.json()
  return data.deleted ?? false
}

// ---------------------------------------------------------------------------
// Conversation edit / fork
// ---------------------------------------------------------------------------

export async function editConversationMessage(conversationId: string, turn: number, newContent: string): Promise<void> {
  const backendUrl = getBackendUrl()
  const response = await fetch(`${backendUrl}/api/conversation/edit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conversation_id: conversationId, turn, new_content: newContent }),
  })
  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(`Failed to edit message: ${response.status} ${errorText.substring(0, 200)}`)
  }
}

export async function truncateConversation(conversationId: string, fromTurn: number): Promise<void> {
  const backendUrl = getBackendUrl()
  const response = await fetch(`${backendUrl}/api/conversation/truncate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conversation_id: conversationId, from_turn: fromTurn }),
  })
  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(`Failed to truncate conversation: ${response.status} ${errorText.substring(0, 200)}`)
  }
}

export async function forkConversation(
  sourceConversationId: string,
  targetConversationId: string,
  upToTurn: number,
): Promise<void> {
  const backendUrl = getBackendUrl()
  const response = await fetch(`${backendUrl}/api/conversation/fork`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source_conversation_id: sourceConversationId,
      target_conversation_id: targetConversationId,
      up_to_turn: upToTurn,
    }),
  })
  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(`Failed to fork conversation: ${response.status} ${errorText.substring(0, 200)}`)
  }
}

// ---------------------------------------------------------------------------
// History database path
// ---------------------------------------------------------------------------

export async function getHistoryPath(): Promise<string> {
  const backendUrl = getBackendUrl()
  const response = await fetch(`${backendUrl}/api/history/path`)
  if (!response.ok) {
    throw new Error(`Failed to get history path: ${response.status}`)
  }
  const data = await response.json()
  return data.path ?? ''
}

export async function setHistoryPath(path: string): Promise<string> {
  const backendUrl = getBackendUrl()
  const response = await fetch(`${backendUrl}/api/history/path`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(`Failed to set history path: ${response.status} ${errorText.substring(0, 200)}`)
  }
  const data = await response.json()
  return data.path ?? path
}

export async function browseDirContents(
  path: string,
): Promise<{
  current_path: string
  parent_path: string | null
  entries: { name: string; path: string; is_dir: boolean }[]
}> {
  const backendUrl = getBackendUrl()
  const url = `${backendUrl}/api/history/browse-dir${path ? `?path=${encodeURIComponent(path)}` : ''}`
  const response = await fetch(url)
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(data.detail ?? `Failed to list directory: ${response.status}`)
  }
  return response.json()
}
