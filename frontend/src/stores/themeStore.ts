/**
 * themeStore — light/dark/system theme preference (Zustand).
 *
 * Spec: design.md §16 (dark mode is class-driven), UI-002.
 *
 * Why this exists rather than a `next-themes`-style provider: the pre-paint
 * bootstrap in `index.html` already sets the `.dark` class before React
 * mounts. This store must therefore *agree* with the DOM rather than fight
 * it, or the first render flips the theme. Seeding `preference` from
 * localStorage (the same key the bootstrap reads) keeps the two in sync.
 *
 * Zustand, not TanStack Query: theme preference is cross-cutting client UI
 * state, never server state (AGENTS.md §5).
 */

import { create } from "zustand";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

/** Must match the key read by the bootstrap script in `index.html`. */
export const THEME_STORAGE_KEY = "theme";
export const DARK_CLASS = "dark";

const isThemePreference = (value: unknown): value is ThemePreference =>
  value === "light" || value === "dark" || value === "system";

/** Returns the stored preference, or null when absent/unreadable. */
export function readStoredPreference(): ThemePreference | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemePreference(raw) ? raw : null;
  } catch {
    // localStorage throws in private browsing modes. OS preference is a
    // safe fallback; the app must still be usable.
    return null;
  }
}

export function systemPrefersDark(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

/** Collapse a preference to the theme actually rendered. */
export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  if (preference === "system") {
    return systemPrefersDark() ? "dark" : "light";
  }
  return preference;
}

export function applyThemeToDocument(resolved: ResolvedTheme): void {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle(DARK_CLASS, resolved === "dark");
}

interface ThemeStore {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  /** Persist an explicit user choice and repaint immediately. */
  setPreference: (preference: ThemePreference) => void;
  /** Re-resolve against the OS preference (called on system change). */
  sync: () => void;
}

const initialPreference: ThemePreference = readStoredPreference() ?? "system";

export const useThemeStore = create<ThemeStore>((set, get) => ({
  preference: initialPreference,
  resolved: resolveTheme(initialPreference),
  setPreference: (preference) => {
    const resolved = resolveTheme(preference);
    applyThemeToDocument(resolved);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, preference);
    } catch {
      // Storage unavailable — the in-memory + DOM change still applies, it
      // just will not survive a reload. Do not surface this to the user.
    }
    set({ preference, resolved });
  },
  sync: () => {
    const { preference, resolved } = get();
    const next = resolveTheme(preference);
    if (next === resolved) return;
    applyThemeToDocument(next);
    set({ resolved: next });
  },
}));