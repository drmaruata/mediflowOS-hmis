/**
 * navigation — pins the "does this nav entry actually go anywhere?" rule and
 * the module inventory.
 *
 * AGENTS.md §5 requires a nav entry with no matching <Route> to be marked
 * `disabled`. This guards against two silent regressions: a nav item pointing
 * at a route that does not exist (blank content area), and a future-release
 * module being shown as navigable when it is not enabled.
 *
 * It also pins coverage: the sidebar is the build backlog made visible, so a
 * backend bounded context dropping out of the inventory is a real defect.
 */

import { describe, expect, it } from "vitest";

import {
  NAV_GROUPS,
  NAV_ITEMS,
  countEnabled,
  isNavItemActive,
  isNavItemDisabled,
  navItemStateLabel,
  type NavItem,
} from "./navigation";

describe("navigation groups", () => {
  it("splits into a main menu and a settings group", () => {
    expect(NAV_GROUPS.map((g) => g.id)).toEqual(["main", "settings"]);
    expect(NAV_GROUPS.map((g) => g.label)).toEqual(["Main Menu", "Settings"]);
  });

  it("has no duplicate ids across groups", () => {
    const ids = NAV_ITEMS.map((i) => i.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("has no duplicate paths across groups", () => {
    const paths = NAV_ITEMS.map((i) => i.path);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it("gives every item a label and an icon for the non-colour encoding", () => {
    for (const entry of NAV_ITEMS) {
      expect(entry.label.length).toBeGreaterThan(0);
      expect(entry.icon).toBeDefined();
    }
  });
});

describe("main menu", () => {
  const main = NAV_GROUPS.find((g) => g.id === "main")!;

  it("prominently lists the eleven clinical modules plus the entry points", () => {
    const labels = main.items.map((i) => i.label);
    for (const expected of [
      "Dashboard",
      "Patient Registration",
      "OPD",
      "IPD",
      "EMR",
      "Emergency",
      "ICU & Live Vitals",
      "Operation Theatre",
      "Laboratory (LIS)",
      "Radiology (RIS)",
      "Pharmacy & Store",
      "Blood Bank",
      "Insurance",
    ]) {
      expect(labels).toContain(expected);
    }
  });

  it("keeps configuration and admin surfaces out of the main menu", () => {
    const labels = main.items.map((i) => i.label);
    for (const excluded of [
      "Users & Roles",
      "Facility Setup",
      "Tariffs",
      "Quality OS",
      "Reports & Exports",
      "Integrations",
      "Platform Tenants",
    ]) {
      expect(labels).not.toContain(excluded);
    }
  });

  it("routes each clinical module to its own bounded context", () => {
    const byModule = new Map(main.items.map((i) => [i.module, i.path]));
    expect(byModule.get("opd")).toBe("/opd");
    expect(byModule.get("ipd")).toBe("/ipd");
    expect(byModule.get("emr")).toBe("/emr");
    expect(byModule.get("emergency")).toBe("/emergency");
    expect(byModule.get("icu")).toBe("/icu");
    expect(byModule.get("ot")).toBe("/ot");
    expect(byModule.get("ris")).toBe("/ris");
    expect(byModule.get("lis")).toBe("/lis");
    expect(byModule.get("pharmacy")).toBe("/pharmacy");
    expect(byModule.get("blood_bank")).toBe("/blood-bank");
    expect(byModule.get("billing_insurance")).toBe("/billing/insurance");
  });
});

describe("module inventory coverage", () => {
  // AGENTS.md §2 backend bounded contexts that own user-facing screens.
  const REQUIRED_MODULES = [
    "dashboard",
    "patient_registry",
    "opd",
    "ipd",
    "emr",
    "lis",
    "ris",
    "pharmacy",
    "blood_bank",
    "billing_insurance",
    "quality_os",
    "emergency",
    "icu",
    "ot",
    "abdm",
    "audit",
    "admin",
    "platform",
    "integration",
  ] as const;

  it("surfaces every user-facing backend module in the sidebar", () => {
    const present = new Set(NAV_ITEMS.map((i) => i.module));
    const missing = REQUIRED_MODULES.filter((m) => !present.has(m));
    expect(missing).toEqual([]);
  });

  it("gives every entry a release so build order is visible", () => {
    for (const entry of NAV_ITEMS) {
      expect(["R1", "R2", "R3", "R4", "R5", "R6", "R7"]).toContain(
        entry.release,
      );
    }
  });
});

describe("entry availability", () => {
  it("marks unimplemented routes disabled rather than navigable", () => {
    const opd = NAV_ITEMS.find((i) => i.id === "opd");
    expect(opd?.path).toBe("/opd");
    expect(isNavItemDisabled(opd!)).toBe(true);
    expect(navItemStateLabel(opd!)).not.toBeNull();
  });

  it("marks only implemented routes as enabled", () => {
    const enabled = NAV_ITEMS.filter((i) => i.availability === "enabled");
    for (const entry of enabled) {
      expect(entry.path).not.toBeNull();
    }
    expect(countEnabled()).toBe(enabled.length);
  });

  it("keeps Dashboard enabled because the route exists", () => {
    const dashboard = NAV_ITEMS.find((i) => i.id === "dashboard");
    expect(dashboard?.path).toBe("/");
    expect(isNavItemDisabled(dashboard!)).toBe(false);
    expect(navItemStateLabel(dashboard!)).toBeNull();
  });

  it("reports future-release modules as not enabled, not merely absent", () => {
    const icu = NAV_ITEMS.find((i) => i.id === "icu");
    expect(icu?.release).toBe("R5");
    expect(navItemStateLabel(icu!)).toBe("Not enabled");
  });

  it("labels every disabled entry with explicit text (design.md §23)", () => {
    for (const entry of NAV_ITEMS.filter(isNavItemDisabled)) {
      expect(navItemStateLabel(entry)).toMatch(/Not enabled|Not available/);
    }
  });
});

describe("isNavItemActive", () => {
  const mk = (path: string | null): NavItem => ({
    id: "x",
    label: "X",
    path,
    icon: NAV_ITEMS[0].icon,
    release: "R1",
    module: "dashboard",
    availability: path === "/" ? "enabled" : "disabled",
  });

  it("matches the root route exactly", () => {
    expect(isNavItemActive(mk("/"), "/")).toBe(true);
    expect(isNavItemActive(mk("/"), "/opd")).toBe(false);
  });

  it("matches nested paths but not sibling prefixes", () => {
    const qos = mk("/quality");
    expect(isNavItemActive(qos, "/quality")).toBe(true);
    expect(isNavItemActive(qos, "/quality/capa")).toBe(true);
    expect(isNavItemActive(qos, "/quality-os")).toBe(false);
  });

  it("never treats a null-path entry as active", () => {
    expect(isNavItemActive(mk(null), "/")).toBe(false);
  });
});