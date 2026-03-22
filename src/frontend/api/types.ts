import { Messages } from '@langchain/langgraph'
import { Ref } from 'vue'

export interface BaseChatCompletionOptions {
  messages: Messages
  errorIssue: Ref<boolean | string | null> // extends string for specific issues
  loading: Ref<boolean>
  maxContextTokens: number
  temperature: number
  llmTimeout: number
  abortSignal?: AbortSignal
  threadId: string
  additionalSystemPrompt?: string // Persistent behavioral instructions appended to system prompt
  conversationId?: string // Enables unified cross-mode conversation history
  attachments?: { filename: string; data: string }[]
  attachmentCharLimit: number
  onStream: (text: string, speaker?: string, forceNew?: boolean) => void
}

export interface OpenAIOptions extends BaseChatCompletionOptions {
  provider: 'openai'
  model?: string
  config: {
    apiKey: string
    baseURL?: string
    dangerouslyAllowBrowser?: boolean
  }
}

export interface OllamaOptions extends BaseChatCompletionOptions {
  provider: 'ollama'
  ollamaModel: string
  ollamaEndpoint?: string
}

export interface GroqOptions extends BaseChatCompletionOptions {
  provider: 'groq'
  groqModel: string
  groqAPIKey: string
}

export interface GeminiOptions extends BaseChatCompletionOptions {
  provider: 'gemini'
  geminiModel?: string
  geminiAPIKey: string
}

export interface AzureOptions extends BaseChatCompletionOptions {
  provider: 'azure'
  azureAPIKey: string
  azureAPIEndpoint: string
  azureDeploymentName: string
  azureAPIVersion?: string
}

export interface LmstudioOptions extends BaseChatCompletionOptions {
  provider: 'lmstudio'
  lmstudioEndpoint?: string
  lmstudioFilterThinking?: boolean
  lmstudioModel?: string
}

export interface AnthropicOptions extends BaseChatCompletionOptions {
  provider: 'anthropic'
  anthropicModel?: string
  anthropicAPIKey: string
}

export interface TogetherAIOptions extends BaseChatCompletionOptions {
  provider: 'togetherai'
  togetheraiModel: string
  togetheraiAPIKey: string
}

export type ProviderOptions =
  | OpenAIOptions
  | OllamaOptions
  | GroqOptions
  | GeminiOptions
  | AzureOptions
  | LmstudioOptions
  | AnthropicOptions
  | TogetherAIOptions

type supportedProviders = 'openai' | 'ollama' | 'groq' | 'gemini' | 'azure' | 'lmstudio' | 'anthropic' | 'togetherai'
// Agent options with tools support
export interface AgentOptions extends BaseChatCompletionOptions {
  provider: supportedProviders
  tools?: any[]
  mcpTools?: string[] // MCP tool names (already in backend format)
  onToolCall?: (toolName: string, args: any) => void
  onToolResult?: (toolName: string, result: string) => void
  onNewBlock?: () => void
  recursionLimit: number
  checkpointId?: string
  // Provider-specific options
  model?: string
  config?: {
    apiKey: string
    baseURL?: string
    dangerouslyAllowBrowser?: boolean
  }
  ollamaModel?: string
  ollamaEndpoint?: string
  groqModel?: string
  groqAPIKey?: string
  geminiModel?: string
  geminiAPIKey?: string
  azureAPIKey?: string
  azureAPIEndpoint?: string
  azureDeploymentName?: string
  azureAPIVersion?: string
  lmstudioEndpoint?: string
  lmstudioFilterThinking?: boolean
  lmstudioModel?: string
  anthropicModel?: string
  anthropicAPIKey?: string
  togetheraiModel?: string
  togetheraiAPIKey?: string
}

// MultiAgent expert configuration
export interface MultiAgentExpertConfig {
  provider: supportedProviders
  model?: string
  temperature: number
  maxContextTokens: number
  // Provider-specific options
  config?: {
    apiKey: string
    baseURL?: string
  }
  ollamaModel?: string
  ollamaEndpoint?: string
  groqModel?: string
  groqAPIKey?: string
  geminiModel?: string
  geminiAPIKey?: string
  azureAPIKey?: string
  azureAPIEndpoint?: string
  azureDeploymentName?: string
  azureAPIVersion?: string
  lmstudioEndpoint?: string
  lmstudioFilterThinking?: boolean
  lmstudioModel?: string
  anthropicModel?: string
  anthropicAPIKey?: string
  togetheraiModel?: string
  togetheraiAPIKey?: string
}

// MultiAgent options
export interface MultiAgentOptions extends BaseChatCompletionOptions {
  mode: 'parallel' | 'collaborative'
  operatingMode?: 'combined' | 'legacy'
  maxRounds: number
  useExpertMemory?: boolean
  expertFullHistory?: boolean
  useExpertParallelization?: boolean
  experts: MultiAgentExpertConfig[]
  overseer: MultiAgentExpertConfig
  synthesizer?: MultiAgentExpertConfig
  formatter?: MultiAgentExpertConfig
  recursionLimit: number
  language?: string
  enabledWordTools?: string[]
  enabledGeneralTools?: string[]
  mcpTools?: string[] // MCP tool names (already in backend format)
  onMessage?: (content: string, speaker?: string, round?: number) => void
  onToolCall?: (toolName: string, args: any, speaker?: string) => void
  onToolResult?: (toolName: string, result: string, speaker?: string) => void
  onOverseerDecision?: (decision: string) => void
}

// MultiAgent configuration for UI settings
export interface MultiAgentConfig {
  mode: 'parallel' | 'collaborative'
  operatingMode: 'combined' | 'legacy'
  maxRounds: number
  expertFullHistory?: boolean
  useExpertParallelization?: boolean
  experts: {
    id: string
    name: string
    provider: supportedProviders
    model: string
    temperature: number
  }[]
  overseer: {
    id: string
    name: string
    provider: supportedProviders
    model: string
    temperature: number
  }
  formatter?: {
    id: string
    provider: supportedProviders
    model: string
    temperature: number
  }
}

// Bot metadata for multiagent message display
export interface BotMetadata {
  botType: 'expert' | 'overseer' | 'synthesizer'
  botName: string // "Expert_1", "Expert_2", "Overseer", "Synthesizer"
  emoji: string // Visual cue: "👤", "🎯", "🔮"
  roundNumber?: number // Round number for collaborative mode
  isDecisionOnly?: boolean // True for overseer decision bubbles (no header)
}
