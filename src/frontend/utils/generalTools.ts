/**
 * Metadata for "general" server-side tools (web search, fetch URL, math, date).
 *
 * Implementations live in the Python backend (src/backend/tools/). The frontend
 * only needs the name + description to render the per-tool enable/disable
 * toggles in the Settings page and to send the active tool list with each
 * agent request.
 */

export type GeneralToolName = 'webSearch' | 'fetchWebContent' | 'getCurrentDate' | 'calculateMath'

export interface GeneralToolDefinition {
  name: GeneralToolName
  description: string
}

export const generalToolDefinitions: GeneralToolDefinition[] = [
  {
    name: 'webSearch',
    description:
      'Search the web for information. Returns relevant search results with snippets.',
  },
  {
    name: 'fetchWebContent',
    description:
      'Fetches content from a given URL. Useful for gathering reference material, quotes, or information to include in the document. Returns the main text content of the webpage.',
  },
  {
    name: 'getCurrentDate',
    description:
      'Get the current date and time in ISO format. Useful when the user asks about today\'s date or wants to insert a timestamp.',
  },
  {
    name: 'calculateMath',
    description:
      'Evaluate a mathematical expression. Supports arithmetic, algebra, and common math functions.',
  },
]

export function getGeneralToolDefinitions(): GeneralToolDefinition[] {
  return generalToolDefinitions
}

export function getGeneralTool(name: GeneralToolName): GeneralToolDefinition | undefined {
  return generalToolDefinitions.find(def => def.name === name)
}
