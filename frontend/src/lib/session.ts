/**
 * Session — the signed-in user's identity and tenant context (UI-001).
 *
 * GET /auth/me/ behind the apiClient, so the session survives token rotation
 * through the same 401-refresh-retry every other call gets. Server state lives
 * in TanStack Query only (AGENTS.md §5); the store stays token-only.
 */

import { useQuery } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";

import { apiClient } from "@/lib/apiClient";
import { useAuthStore } from "@/stores/authStore";

export interface Session {
  username: string;
  tenant_id: string | null;
  facility_id: string | null;
  role: string | null;
  permissions: string[];
  allows_break_glass: boolean;
  requires_mfa: boolean;
  mfa_verified: boolean;
}

export async function fetchSession(): Promise<Session> {
  return apiClient<Session>("/api/v1/auth/me/");
}

export function useSession(): UseQueryResult<Session> {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: fetchSession,
    enabled: isAuthenticated,
    // The apiClient already retries once after refreshing a 401; queue-level
    // retries would re-run a dead session before the guard can redirect.
    retry: false,
  });
}
