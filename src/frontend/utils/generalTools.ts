/**
 * Names of the "general" server-side tools (web search, fetch URL, math, date).
 *
 * Implementations AND metadata live in the Python backend (src/backend/tools/).
 * Names and descriptions reach the UI through the `/api/tools` manifest
 * (src/frontend/api/toolManifest.ts) — this type exists only so the frontend
 * can talk about the stored `enabledGeneralTools` selection in camelCase.
 */

export type GeneralToolName = 'webSearch' | 'fetchWebContent' | 'getCurrentDate' | 'calculateMath'
