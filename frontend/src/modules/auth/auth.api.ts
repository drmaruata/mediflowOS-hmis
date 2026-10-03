/**
 * Auth API — login / logout / token refresh (TEN-010, REG-001).
 *
 * SimpleJWT is the token backend. Tokens are short-lived; refresh token is
 * stored in sessionStorage via authStore. Never log token values.
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

export async function login(payload: LoginPayload): Promise<TokenPair> {
  return apiClient<TokenPair>("/api/v1/auth/token/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function refreshAccessToken(refresh: string): Promise<{ access: string }> {
  return apiClient<{ access: string }>("/api/v1/auth/token/refresh/", {
    method: "POST",
    body: JSON.stringify({ refresh }),
  });
}

export async function logout(refresh: string): Promise<void> {
  await apiClient<void>("/api/v1/auth/token/blacklist/", {
    method: "POST",
    body: JSON.stringify({ refresh }),
  });
}
