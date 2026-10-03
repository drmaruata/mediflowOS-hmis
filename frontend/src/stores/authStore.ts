/**
 * authStore — Zustand store for cross-cutting authentication UI state.
 *
 * Persists the JWT access and refresh tokens to sessionStorage so they survive
 * page refreshes but are cleared when the browser tab is closed.
 * Server state (user profile, tenant info) lives in TanStack Query, not here.
 */

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  setTokens: (access: string, refresh: string) => void;
  clearTokens: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,

      setTokens: (access, refresh) =>
        set({ accessToken: access, refreshToken: refresh, isAuthenticated: true }),

      clearTokens: () =>
        set({ accessToken: null, refreshToken: null, isAuthenticated: false }),
    }),
    {
      name: "mediflow-auth",
      storage: createJSONStorage(() => sessionStorage),
      // Only persist tokens, not derived booleans — they rehydrate from tokens.
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        isAuthenticated: state.isAuthenticated,
      }),
    },
  ),
);
