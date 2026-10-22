/**
 * styles — contrast assertions for the shipped token pairs.
 *
 * Spec: UI_UX_design §5.2 ("CI must calculate the actual shipped CSS token
 * contrast in both themes and fail on any normal-text pair below 4.5:1"),
 * design.md §23 (WCAG 2.1 AA).
 *
 * jsdom cannot compute Tailwind class colours, so these assert the token
 * values directly, parsed straight out of theme.css / globals.css so a test
 * cannot pass against a stale copy.
 *
 * Medicore restyle (2026-10-22): the application chrome is THEME-SCOPED —
 * light values in `:root`, dark values in `.dark`. The previous invariant
 * ("shell tokens stay fixed navy in both themes") is intentionally inverted:
 * both blocks must now carry the chrome tokens, and the pair-strength floor
 * (4.5:1 normal text / >1.05 surface boundary) still applies per theme.
 * Spec: docs/superpowers/specs/2026-10-22-medicore-restyle-design.md §4.2–§4.3.
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// Resolved from the Vitest root (frontend/) rather than import.meta.url,
// which is not a file: URL under the jsdom environment.
const themeCss = readFileSync(
  resolve(process.cwd(), "src/styles/theme.css"),
  "utf8",
);
const globalsCss = readFileSync(
  resolve(process.cwd(), "src/styles/globals.css"),
  "utf8",
);

/** Isolate a flat `{ ... }` block (no nested braces in these blocks). */
function sliceBlock(css: string, opener: string): string {
  const start = css.indexOf(`${opener} {`);
  if (start < 0) throw new Error(`block ${opener} not found`);
  const end = css.indexOf("}", start);
  return css.slice(start, end);
}

const lightTheme = sliceBlock(themeCss, ":root");
const darkTheme = sliceBlock(themeCss, ".dark");
const lightGlobals = sliceBlock(globalsCss, ":root");
const darkGlobals = sliceBlock(globalsCss, ".dark");

/** Read a `--token` value (hex or rgba) out of a block. */
function token(block: string, name: string): string {
  const match = block.match(
    new RegExp(
      `${name}:\\s*((?:#[0-9a-fA-F]{3,8})|(?:rgba?\\(\\s*\\d+(?:,\\s*\\d+){2}(?:,\\s*(?:0|1|0?\\.\\d+)\\s*)?\\)))`,
    ),
  );
  if (!match) throw new Error(`token ${name} not found`);
  return match[1];
}

/**
 * Read a bare `S L% L%` HSL triplet (the globals.css convention) and convert
 * it to [r, g, b] so the same contrast math applies to every token kind.
 */
function tripletToRgb(block: string, name: string): [number, number, number] {
  const match = block.match(new RegExp(`${name}:\\s*([\\d.]+) ([\\d.]+)% ([\\d.]+)%`));
  if (!match) throw new Error(`triplet ${name} not found`);
  const [, h, s, l] = match;
  const H = ((parseFloat(h) % 360) + 360) % 360;
  const S = parseFloat(s) / 100;
  const L = parseFloat(l) / 100;
  const c = (1 - Math.abs(2 * L - 1)) * S;
  const hp = H / 60;
  const x = c * (1 - Math.abs((hp % 2) - 1));
  let [r, g, b] =
    hp < 1 ? [c, x, 0]
    : hp < 2 ? [x, c, 0]
    : hp < 3 ? [0, c, x]
    : hp < 4 ? [0, x, c]
    : hp < 5 ? [x, 0, c]
    : [0, 0, c];
  const m = L - c / 2;
  // 0-255 channels so the shared luminance/contrast maths applies unchanged.
  return [(r + m) * 255, (g + m) * 255, (b + m) * 255].map(Math.round) as [
    number,
    number,
    number,
  ];
}

function hexToRgb(hex: string): [number, number, number] {
  let h = hex.replace("#", "");
  if (h.length === 3) {
    h = h
      .split("")
      .map((c) => c + c)
      .join("");
  }
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ] as [number, number, number];
}

function relativeLuminance(rgb: [number, number, number]): number {
  const [r, g, b] = rgb.map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** rgba() -> rgb over the given opaque background (alpha compositing). */
function overRgba(rgba: string, backdrop: string): [number, number, number] {
  const m = rgba.match(/rgba?\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)/);
  if (!m) throw new Error(`not an rgba value: ${rgba}`);
  const [, r, g, b, a] = m;
  const [br, bg, bb] = hexToRgb(backdrop);
  const f = parseFloat(a);
  const mix = (fg: string, bg: number) =>
    Math.round(f * Number(fg) + (1 - f) * bg);
  return [mix(r, br), mix(g, bg), mix(b, bb)] as [number, number, number];
}

type RgbLike = string | [number, number, number];

/** Hex|rgba strings parse to channels; [r,g,b] already is one. */
function luminanceOf(v: RgbLike): number {
  if (typeof v === "string") {
    if (v.startsWith("#")) return relativeLuminance(hexToRgb(v));
    if (v.startsWith("rgb")) {
      // Soft fills composite over white for the lower-bound check.
      return relativeLuminance(overRgba(v, "#FFFFFF"));
    }
    throw new Error(`unsupported colour value: ${v}`);
  }
  return relativeLuminance(v);
}

function contrast(a: RgbLike, b: RgbLike): number {
  const l1 = luminanceOf(a);
  const l2 = luminanceOf(b);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

const WHITE = "#FFFFFF";

describe("shell palette contrast (WCAG 2.1 AA) — light chrome", () => {
  it("navigation label on the rail >= 4.5:1 (#17212B on #FBFDFD)", () => {
    expect(
      contrast(token(lightTheme, "--shell-sidebar-foreground"), token(lightTheme, "--shell-sidebar")),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it("rail section labels on the soft tier >= 4.5:1 (the faint mock tier cannot carry meaning)", () => {
    expect(
      contrast(token(lightTheme, "--shell-sidebar-subtle"), token(lightTheme, "--shell-sidebar")),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it("active entry label on the accent-soft fill >= 4.5:1", () => {
    expect(
      contrast(token(lightTheme, "--shell-active-foreground"), token(lightTheme, "--shell-active")),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it("topbar controls on the topbar >= 4.5:1", () => {
    expect(
      contrast(token(lightTheme, "--shell-topbar-foreground"), token(lightTheme, "--shell-topbar")),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it("rail hover fill stays distinguishable from the rail surface", () => {
    // Non-text boundary must clear the boundary floor (spec §4.3).
    expect(
      contrast(token(lightTheme, "--shell-sidebar-hover"), token(lightTheme, "--shell-sidebar")),
    ).toBeGreaterThan(1.05);
  });

  it("primary button label on its fill >= 4.5:1 (globals.css triplets)", () => {
    expect(
      contrast(tripletToRgb(lightGlobals, "--primary-foreground"), tripletToRgb(lightGlobals, "--primary")),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it("green text ink >= 4.5:1 on white in light mode", () => {
    // The mock's #18c58d/#0eac77 are fill greens (≈2.2:1/2.9:1); text uses
    // the ink tier instead (spec §4.3).
    expect(contrast(token(lightTheme, "--brand-accent-ink"), WHITE)).toBeGreaterThanOrEqual(4.5);
  });

  it("content text pairs with the card surface — inputs render bg-card (light)", () => {
    // Regression net for the C1 review finding: .dark --background is the
    // approved light canvas, so no text may sit on it. Inputs, minis and
    // selects pair with --card; pin the pairs they rely on.
    expect(
      contrast(tripletToRgb(lightGlobals, "--foreground"), tripletToRgb(lightGlobals, "--card")),
    ).toBeGreaterThanOrEqual(4.5);
    expect(
      contrast(tripletToRgb(lightGlobals, "--muted-foreground"), tripletToRgb(lightGlobals, "--card")),
    ).toBeGreaterThanOrEqual(4.5);
  });
});

describe("shell palette contrast — dark chrome", () => {
  it("navigation label on the rail >= 4.5:1", () => {
    expect(
      contrast(token(darkTheme, "--shell-sidebar-foreground"), token(darkTheme, "--shell-sidebar")),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it("rail section labels on the soft tier >= 4.5:1", () => {
    expect(
      contrast(token(darkTheme, "--shell-sidebar-subtle"), token(darkTheme, "--shell-sidebar")),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it("topbar controls on the topbar >= 4.5:1", () => {
    expect(
      contrast(token(darkTheme, "--shell-topbar-foreground"), token(darkTheme, "--shell-topbar")),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it("active entry label on the active fill >= 4.5:1", () => {
    expect(
      contrast(token(darkTheme, "--shell-active-foreground"), token(darkTheme, "--shell-active")),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it("primary button label on its fill >= 4.5:1 (dark)", () => {
    expect(
      contrast(tripletToRgb(darkGlobals, "--primary-foreground"), tripletToRgb(darkGlobals, "--primary")),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it("green text ink >= 4.5:1 on the dark card surface", () => {
    expect(
      contrast(token(darkTheme, "--brand-accent-ink"), tripletToRgb(darkGlobals, "--card")),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it("content text pairs with the card surface — inputs render bg-card (dark)", () => {
    // Same net as light: --foreground/--muted-foreground carry text on
    // --card, never on the light canvas --background (1.4:1 by design).
    expect(
      contrast(tripletToRgb(darkGlobals, "--foreground"), tripletToRgb(darkGlobals, "--card")),
    ).toBeGreaterThanOrEqual(4.5);
    expect(
      contrast(tripletToRgb(darkGlobals, "--muted-foreground"), tripletToRgb(darkGlobals, "--card")),
    ).toBeGreaterThanOrEqual(4.5);
  });
});

describe("theme-independence guard — inverted for the theme-scoped chrome", () => {
  // The old guard forbade chrome tokens in the dark block because the rail
  // was fixed navy. The Medicore chrome IS dark navy only in dark mode, so
  // BOTH blocks must declare them and the two blocks must disagree — if the
  // chrome ever collapses back into one theme, light mode regresses to the
  // original dark-labels-on-navy bug.
  for (const name of [
    "--shell-sidebar-foreground",
    "--shell-sidebar-subtle",
    "--shell-topbar-foreground",
  ]) {
    it(`${name} is theme-scoped: present in light AND dark`, () => {
      expect(token(lightTheme, name)).toBeTruthy();
      expect(token(darkTheme, name)).toBeTruthy();
      expect(token(lightTheme, name)).not.toBe(token(darkTheme, name));
    });
  }

  it("themes the dashboard canvas so dark mode has no white canvas", () => {
    expect(darkTheme).toContain("--canvas-dashboard:");
    expect(darkTheme).toContain("--surface:");
    expect(darkTheme).toContain("--text-primary:");
  });
});
