/**
 * apiClient — base fetch wrapper for authenticated API calls.
 *
 * Reads the JWT access token from authStore and injects it as a Bearer header.
 * Throws a typed ApiError on non-2xx responses so callers never silently swallow
 * failures (AGENTS.md §5 data-fetching rules).
 */

import { useAuthStore } from "@/stores/authStore";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export async function apiClient<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const token = useAuthStore.getState().accessToken;

  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });

  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText);
    throw new ApiError(response.status, text);
  }

  // 204 No Content — return empty object cast to T.
  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}
