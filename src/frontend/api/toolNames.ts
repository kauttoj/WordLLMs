/**
 * Tool name mapping (frontend camelCase <-> backend snake_case).
 * Leaf module: must not import anything, so it can be shared by
 * `toolManifest.ts` and `backend.ts` without creating a circular import.
 *
 * All 28 Word tools are exact camelCase<->snake_case pairs (e.g. `insertText`
 * <-> `insert_text`), so a single regex handles them. Only the 4 general
 * tools (web search, fetch, date, calculator) have irregular names and need
 * an explicit table.
 *
 * MCP tool names (`mcp_<server>_<originalName>`) are already in backend
 * format and their `<originalName>` segment is frequently camelCase (e.g.
 * `mcp_context7_resolveLibraryId`), so they must bypass conversion entirely
 * in both directions — otherwise the regex would mangle the embedded name.
 */

const IRREGULAR: Record<string, string> = {
  webSearch: 'web_search',
  fetchWebContent: 'fetch_url',
  getCurrentDate: 'get_current_date',
  calculateMath: 'calculate',
}
const IRREGULAR_REVERSE: Record<string, string> = Object.fromEntries(
  Object.entries(IRREGULAR).map(([k, v]) => [v, k]),
)

/** Frontend camelCase -> backend snake_case. MCP names pass through untouched. */
export function toBackendName(n: string): string {
  if (n.startsWith('mcp_')) return n
  return IRREGULAR[n] ?? n.replace(/[A-Z]/g, c => `_${c.toLowerCase()}`)
}

/** Backend snake_case -> frontend camelCase. MCP names pass through untouched. */
export function toFrontendName(n: string): string {
  if (n.startsWith('mcp_')) return n
  return IRREGULAR_REVERSE[n] ?? n.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase())
}
