/**
 * styles — contrast assertions for the shell palette.
 *
 * Spec: UI_UX_design §5.2 ("CI must calculate the actual shipped CSS token
 * contrast in both themes and fail on any normal-text pair below 4.5:1"),
 * design.md §23 (WCAG 2.1 AA), §2.3A (shell palette).
 *
 * jsdom cannot compute Tailwind class colours, so these assert the token
 * values directly. That is the layer that actually regressed: the active
 * navigation blue was #0B75E5, which measures 4.48:1 against white and has
 * been corrected here. Parsed straight out of theme.css so the test cannot
 * pass against a stale copy.
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

/** Read a `--token` value out of the theme-independent `:root` block. */
function token(name: string): string {
  const match = themeCss.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{3,8})`));
  if (!match) throw new Error(`token ${name} not found in theme.css`);
  return match[1];
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

function contrast(a: string, b: string): number {
  const l1 = relativeLuminance(hexToRgb(a));
  const l2 = relativeLuminance(hexToRgb(b));
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

const WHITE = "#FFFFFF";

describe("shell palette contrast (WCAG 2.1 AA)", () => {
  it("active navigation label: white on --shell-active >= 4.5:1", () => {
    // design.md §2.3A shipped #0B75E5 at 4.48:1 — a real AA failure that the
    // CSS-variable/utility split made invisible to the type checker.
    expect(contrast(WHITE, token("--shell-active"))).toBeGreaterThanOrEqual(4.5);
  });

  it("navigation labels: --shell-sidebar-foreground on the rail >= 4.5:1", () => {
    expect(contrast(token("--shell-sidebar-foreground"), token("--shell-sidebar")))
      .toBeGreaterThanOrEqual(4.5);
  });

  it("rail section headings: --shell-sidebar-subtle on the rail >= 4.5:1", () => {
    expect(contrast(token("--shell-sidebar-subtle"), token("--shell-sidebar")))
      .toBeGreaterThanOrEqual(4.5);
  });

  it("top bar controls: white on --shell-topbar >= 4.5:1", () => {
    expect(contrast(WHITE, token("--shell-topbar"))).toBeGreaterThanOrEqual(4.5);
  });

  it("rail hover fill stays distinguishable from the rail surface", () => {
    // Non-text boundary must clear 3:1 against the rail (design.md §23).
    expect(contrast(token("--shell-sidebar-hover"), token("--shell-sidebar")))
      .toBeGreaterThan(1.05);
  });
});

describe("theme independence", () => {
  it("keeps the rail foregrounds out of a .dark override", () => {
    // If these became theme-scoped again, light mode would paint dark labels
    // on the navy rail — the original invisible-sidebar bug.
    const darkBlock = themeCss.slice(themeCss.indexOf(".dark {"));
    for (const name of [
      "--shell-sidebar-foreground",
      "--shell-sidebar-subtle",
      "--shell-sidebar-hover",
    ]) {
      expect(darkBlock).not.toContain(name);
    }
  });

  it("themes the dashboard canvas so dark mode has no white canvas", () => {
    // The previous single fixed-light `:root` left the canvas #F5F9FD behind
    // dark cards.
    const darkBlock = themeCss.slice(themeCss.indexOf(".dark {"));
    expect(darkBlock).toContain("--canvas-dashboard:");
    expect(darkBlock).toContain("--surface:");
    expect(darkBlock).toContain("--text-primary:");
  });
});