/**
 * Backend URL configuration.
 * Leaf module: must not import from anywhere else in `src/frontend/api/`
 * so it can be depended on by both `toolManifest.ts` and `backend.ts` without
 * creating a circular import.
 */

// Backend URL - empty string means same origin (relative paths)
// Set to 'http://localhost:8000' for development with separate servers
const DEFAULT_BACKEND_URL = ''

export function getBackendUrl(): string {
  return localStorage.getItem('backendUrl') ?? DEFAULT_BACKEND_URL
}

export function setBackendUrl(url: string): void {
  localStorage.setItem('backendUrl', url)
}
