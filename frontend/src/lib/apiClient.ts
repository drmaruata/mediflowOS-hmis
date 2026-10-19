/**
 * apiClient — base fetch wrapper for authenticated API calls (UI-001).
 *
 * Reads the JWT access token from authStore and injects it as a Bearer header.
 * Throws a typed ApiError on non-2xx responses so callers never silently swallow
 * failures (AGENTS.md §5 data-fetching rules). A 401 on a bearer-authenticated
 * call triggers one single-flight refresh (see tokenRefresh.ts) and exactly one
 * retry with the rotated token; the retry itself cannot refresh again.
 */

import { useAuthStore } from "@/stores/authStore";
import { refreshSession } from "@/lib/tokenRefresh";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ApiClientOptions {
  /**
   * Opt out of the 401 refresh-retry. The token lifecycle endpoints
   * (login/refresh/blacklist) manage the session themselves: refreshing in
   * response to their own 401s would recurse, and a failed login must not
   * retry with a different credential.
   */
  skipRefresh?: boolean;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

async function doFetch(path: string, init: RequestInit): Promise<Response> {
  const token = useAuthStore.getState().accessToken;

  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  return fetch(`${API_BASE}${path}`, { ...init, headers });
}

async function parseResponse<T>(response: Response): Promise<T> {
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

export async function apiClient<T>(
  path: string,
  init: RequestInit = {},
  options: ApiClientOptions = {},
): Promise<T> {
  const response = await doFetch(path, init);

  if (options.skipRefresh || response.status !== 401) {
    return parseResponse<T>(response);
  }

  const refreshed = await refreshSession();
  if (!refreshed) {
    // Dead session: clearTokens() has already flipped the store, so the
    // AuthGuard drives the redirect; surface the original 401 to the caller.
    return parseResponse<T>(response);
  }

  // doFetch re-reads the store, so the retry carries the rotated token and
  // can only fail once more — no refresh loop by construction.
  return parseResponse<T>(await doFetch(path, init));
}
