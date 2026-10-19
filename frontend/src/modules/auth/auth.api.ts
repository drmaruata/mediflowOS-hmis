/**
 * Auth API — login / logout / token refresh / second factor (TEN-010, REG-001, UI-001).
 *
 * SimpleJWT is the token backend. Tokens are short-lived; refresh token is
 * stored in sessionStorage via authStore. Never log token values.
 *
 * The token-lifecycle calls pass skipRefresh: the 401 interceptor exists to
 * recover expired sessions, and these endpoints are how the session itself is
 * established, rotated and retired.
 */

import { apiClient } from "@/lib/apiClient";

export interface LoginPayload {
  username: string;
  password: string;
}

export interface TokenPair {
  access: string;
  refresh: string;
}

/** SimpleJWT's refresh body; `refresh` is present only when rotation is on. */
export interface RefreshedAccess {
  access: string;
  refresh?: string;
}

export interface MfaDevice {
  persistent_id: string;
  name: string;
  confirmed: boolean;
  config_url: string | null;
}

export async function login(payload: LoginPayload): Promise<TokenPair> {
  return apiClient<TokenPair>(
    "/api/v1/auth/token/",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    { skipRefresh: true },
  );
}

export async function refreshAccessToken(refresh: string): Promise<RefreshedAccess> {
  return apiClient<RefreshedAccess>(
    "/api/v1/auth/token/refresh/",
    {
      method: "POST",
      body: JSON.stringify({ refresh }),
    },
    { skipRefresh: true },
  );
}

export async function logout(refresh: string): Promise<void> {
  await apiClient<void>(
    "/api/v1/auth/token/blacklist/",
    {
      method: "POST",
      body: JSON.stringify({ refresh }),
    },
    { skipRefresh: true },
  );
}

export async function listMfaDevices(): Promise<MfaDevice[]> {
  return apiClient<MfaDevice[]>("/api/v1/mfa-devices/");
}

export async function confirmMfaDevice(
  persistentId: string,
  token: string,
): Promise<void> {
  await apiClient<void>(`/api/v1/mfa-devices/${persistentId}/confirm/`, {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}
