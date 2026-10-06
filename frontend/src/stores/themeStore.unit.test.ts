/**
 * themeStore — pins the pure theme-resolution rules.
 *
 * The bug this guards: dark mode is class-driven (design.md §16), so the
 * theme has to be derived from the stored preference and the OS setting in
 * one place. If `resolveTheme` drifts, the app paints dark surfaces over
 * light-theme text — the failure that made the login page unreadable.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DARK_CLASS,
  THEME_STORAGE_KEY,
  applyThemeToDocument,
  readStoredPreference,
  resolveTheme,
  systemPrefersDark,
  useThemeStore,
  type ThemePreference,
} from "./themeStore";

function mockPrefersDark(value: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("dark") && value,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
}

describe("resolveTheme", () => {
  beforeEach(() => {
    mockPrefersDark(false);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("passes explicit preferences straight through", () => {
    expect(resolveTheme("light")).toBe("light");
    expect(resolveTheme("dark")).toBe("dark");
  });

  it("resolves 'system' from the OS preference", () => {
    mockPrefersDark(true);
    expect(resolveTheme("system")).toBe("dark");
    mockPrefersDark(false);
    expect(resolveTheme("system")).toBe("light");
  });

  it("never resolves to anything but light/dark", () => {
    const results: ThemePreference[] = ["light", "dark", "system"];
    for (const p of results) {
      expect(["light", "dark"]).toContain(resolveTheme(p));
    }
  });
});

describe("readStoredPreference", () => {
  afterEach(() => {
    localStorage.clear();
  });

  it("returns null when nothing is stored", () => {
    expect(readStoredPreference()).toBeNull();
  });

  it("returns the stored preference", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    expect(readStoredPreference()).toBe("dark");
  });

  it("rejects a corrupt stored value instead of trusting it", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "chartreuse");
    expect(readStoredPreference()).toBeNull();
  });
});

describe("applyThemeToDocument", () => {
  afterEach(() => {
    document.documentElement.classList.remove(DARK_CLASS);
  });

  it("adds the dark class for dark and removes it for light", () => {
    applyThemeToDocument("dark");
    expect(document.documentElement.classList.contains(DARK_CLASS)).toBe(true);
    applyThemeToDocument("light");
    expect(document.documentElement.classList.contains(DARK_CLASS)).toBe(false);
  });

  it("is idempotent — StrictMode double-invoke must be safe", () => {
    applyThemeToDocument("dark");
    applyThemeToDocument("dark");
    expect(document.documentElement.classList.contains(DARK_CLASS)).toBe(true);
  });
});

describe("systemPrefersDark", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("is false when matchMedia is unavailable", () => {
    vi.stubGlobal("matchMedia", undefined);
    expect(systemPrefersDark()).toBe(false);
  });
});

describe("store actions", () => {
  beforeEach(() => {
    mockPrefersDark(false);
    localStorage.clear();
    document.documentElement.classList.remove(DARK_CLASS);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("setPreference persists the choice and repaints the DOM", () => {
    useThemeStore.getState().setPreference("dark");
    expect(useThemeStore.getState().preference).toBe("dark");
    expect(useThemeStore.getState().resolved).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.classList.contains(DARK_CLASS)).toBe(true);
  });

  it("persists 'system' verbatim so a reload can re-derive it", () => {
    useThemeStore.getState().setPreference("system");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("system");
    expect(useThemeStore.getState().resolved).toBe("light");
  });

  it("sync() follows an OS flip while the preference is 'system'", () => {
    useThemeStore.getState().setPreference("system");
    expect(useThemeStore.getState().resolved).toBe("light");

    mockPrefersDark(true);
    useThemeStore.getState().sync();

    expect(useThemeStore.getState().resolved).toBe("dark");
    expect(document.documentElement.classList.contains(DARK_CLASS)).toBe(true);
  });

  it("sync() does not override an explicit choice when the OS flips", () => {
    useThemeStore.getState().setPreference("light");
    mockPrefersDark(true);
    useThemeStore.getState().sync();
    expect(useThemeStore.getState().resolved).toBe("light");
  });
});