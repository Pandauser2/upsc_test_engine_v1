/**
 * API client base URL for FastAPI backend.
 * Used by auth and document/test calls when Step 10 is implemented.
 */
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}
