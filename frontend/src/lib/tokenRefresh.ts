/**
 * tokenRefresh — single-flight session refresh for concurrent 401s (UI-001).
 *
 * One module-level in-flight Promise: N simultaneous 401s await the same
 * rotation instead of racing it (a second refresh would burn the refresh token
 * the first one just rotated in, logging everyone out). On failure the store
 * is cleared here so the AuthGuard — not a window.location hack — sends the
 * user to the sign-in route.
 */

import { refreshAccessToken } from "@/modules/auth/auth.api";
import { useAuthStore } from "@/stores/authStore";

let inFlight: Promise<boolean> | null = null;

/** All callers share the refresh currently in flight; null when idle. */
export function refreshSession(): Promise<boolean> {
  if (!inFlight) {
    inFlight = refresh().finally(() => {
      inFlight = null;
    });
  }
  return inFlight;
}

async function refresh(): Promise<boolean> {
  const { refreshToken, setTokens, clearTokens } = useAuthStore.getState();
  if (!refreshToken) {
    clearTokens();
    return false;
  }
  try {
    const data = await refreshAccessToken(refreshToken);
    // The backend rotates; keep the old refresh token only if it did not.
    setTokens(data.access, data.refresh ?? refreshToken);
    return true;
  } catch {
    clearTokens();
    return false;
  }
}
