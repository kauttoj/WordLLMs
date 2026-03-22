type IStringKeyMap = Record<string, any>

type supportedPlatforms = 'openai' | 'azure' | 'gemini' | 'ollama' | 'groq' | 'anthropic' | 'lmstudio' | 'togetherai'

type insertTypes = 'replace' | 'append' | 'newLine' | 'NoAction'

interface ToolInputSchema {
  type: 'object'
  properties: Record<string, ToolProperty>
  required?: string[]
}

interface ToolProperty {
  type: 'string' | 'number' | 'boolean' | 'array' | 'object'
  description?: string
  enum?: string[]
  items?: ToolProperty
  default?: any
}
interface WordToolDefinition {
  name: string
  description: string
  inputSchema: ToolInputSchema
  execute: (args: Record<string, any>) => Promise<string>
}
