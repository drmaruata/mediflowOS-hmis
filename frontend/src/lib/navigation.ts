/**
 * navigation — application-shell navigation model.
 *
 * Spec: design.md §5.3 (240px rail / 72px collapsed, grouped navigation),
 * §2.3A (dark navy rail, blue active state), §8.0/§8.1,
 * AGENTS.md §5 ("a nav entry with no matching <Route> renders a blank
 * content area — mark it `disabled` until its module exists").
 *
 * STRUCTURE: `main` holds the day-to-day clinical modules a doctor, nurse or
 * technician opens first — the eleven bounded contexts from AGENTS.md §2 that
 * carry live clinical work, plus Dashboard and Patient Registration. Anything
 * that is configuration, accreditation, finance admin or platform plumbing
 * lives under `settings` so the rail does not read as one long undifferentiated
 * list (design.md §5.3 requires distinct section labels).
 *
 * Every backend bounded context appears exactly once, so the sidebar doubles
 * as the build backlog: each entry carries its release and owning module
 * folder. Building module X means adding its path to `IMPLEMENTED_ROUTES`;
 * the resolver then flips it from placeholder to a working link.
 *
 * design.md §8.1 rail entries with no backend bounded context are folded into
 * their owning module rather than inventing apps: Store → pharmacy,
 * Sterilization → OT (CSSD).
 */

import type { LucideIcon } from "lucide-react";
import {
  Activity,
  AlertTriangle,
  BadgeIndianRupee,
  BedDouble,
  Bell,
  Building2,
  ClipboardCheck,
  ClipboardList,
  CreditCard,
  FileSpreadsheet,
  FlaskConical,
  LayoutDashboard,
  Microscope,
  Package,
  Plug,
  QrCode,
  Receipt,
  ScanLine,
  ScrollText,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Stethoscope,
  Syringe,
  TestTube2,
  UserRoundSearch,
  Users,
  UsersRound,
  Wand2,
} from "lucide-react";

export type NavAvailability = "enabled" | "disabled" | "notEnabled";

/** Release ownership, per UI_UX_design §18.2 screen inventory. */
export type Release = "R1" | "R2" | "R3" | "R4" | "R5" | "R6" | "R7";

export interface NavItem {
  id: string;
  label: string;
  /** Path relative to the shell; null when no route exists yet. */
  path: string | null;
  icon: LucideIcon;
  /** Availability decided by the resolver, not authored by hand. */
  availability: NavAvailability;
  release: Release;
  /** Owning frontend module folder, mirroring the backend app name. */
  module: string;
}

export interface NavGroup {
  id: string;
  /** Section heading rendered above the group. */
  label: string;
  items: NavItem[];
}

/**
 * Routes that actually exist in the router today. Kept as an explicit set
 * rather than read from React Router so this module stays pure.
 */
export const IMPLEMENTED_ROUTES: ReadonlySet<string> = new Set(["/"]);

/**
 * Tenant-enabled module ids. Absent module ⇒ `notEnabled` (R4-R7 gating,
 * design.md §5.3). Everything R1-R3 ships enabled by default.
 */
const TENANT_ENABLED_MODULES: ReadonlySet<string> = new Set();

/** R4-R7 are the releases a tenant can switch on (UI_UX_design §10). */
const FUTURE_RELEASES: ReadonlySet<Release> = new Set<Release>([
  "R4",
  "R5",
  "R6",
  "R7",
]);

function resolveAvailability(
  path: string | null,
  release: Release,
): NavAvailability {
  if (path !== null && IMPLEMENTED_ROUTES.has(path)) return "enabled";
  if (FUTURE_RELEASES.has(release)) {
    // Configured but unbuilt ⇒ still not navigable; report it as gated.
    return TENANT_ENABLED_MODULES.has(path ?? "") ? "disabled" : "notEnabled";
  }
  return "disabled";
}

function item(
  id: string,
  label: string,
  path: string,
  icon: LucideIcon,
  release: Release,
  module: string,
): NavItem {
  return {
    id,
    label,
    path,
    icon,
    release,
    module,
    availability: resolveAvailability(path, release),
  };
}

/**
 * Main menu — the eleven clinical modules plus the two entry points every
 * user needs on arrival. Ordered roughly by daily touch frequency.
 */
const MAIN_ITEMS: NavItem[] = [
  item("dashboard", "Dashboard", "/", LayoutDashboard, "R1", "dashboard"),
  item(
    "patients",
    "Patient Registration",
    "/patients",
    UserRoundSearch,
    "R1",
    "patient_registry",
  ),
  item("opd", "OPD", "/opd", Stethoscope, "R2", "opd"),
  item("ipd", "IPD", "/ipd", BedDouble, "R2", "ipd"),
  item("emr", "EMR", "/emr", ClipboardList, "R2", "emr"),
  item("emergency", "Emergency", "/emergency", AlertTriangle, "R5", "emergency"),
  item("icu", "ICU & Live Vitals", "/icu", Activity, "R5", "icu"),
  item("ot", "Operation Theatre", "/ot", ClipboardCheck, "R5", "ot"),
  item("lis", "Laboratory (LIS)", "/lis", FlaskConical, "R4", "lis"),
  item("ris", "Radiology (RIS)", "/ris", TestTube2, "R4", "ris"),
  item("pharmacy", "Pharmacy & Store", "/pharmacy", Package, "R4", "pharmacy"),
  item("blood-bank", "Blood Bank", "/blood-bank", Syringe, "R4", "blood_bank"),
  item("insurance", "Insurance", "/billing/insurance", Receipt, "R6", "billing_insurance"),
];

const SETTINGS_ITEMS: NavItem[] = [
  // Finance administration
  item("billing", "Billing", "/billing", BadgeIndianRupee, "R2", "billing_insurance"),
  item("tariffs", "Tariffs", "/billing/tariffs", CreditCard, "R2", "billing_insurance"),
  item("claims", "Claims & TPA", "/billing/claims", ScrollText, "R6", "billing_insurance"),

  // Quality & compliance
  item("quality-os", "Quality OS", "/quality", ShieldCheck, "R3", "quality_os"),
  item("capa", "CAPA", "/quality/capa", Wand2, "R3", "quality_os"),
  item("data-quality", "Data Quality", "/quality/data-quality", Microscope, "R3", "quality_os"),
  item("alerts", "Alerts", "/quality/alerts", Bell, "R3", "quality_os"),
  item(
    "assessments",
    "Assessments (NQAS/NABH)",
    "/quality/assessments",
    ClipboardCheck,
    "R7",
    "quality_os",
  ),
  item("reports", "Reports & Exports", "/quality/reports", FileSpreadsheet, "R3", "quality_os"),

  // Facility configuration
  item("users", "Users & Roles", "/admin/users", Users, "R1", "admin"),
  item("departments", "Departments", "/admin/departments", Building2, "R1", "admin"),
  item("wards-beds", "Wards & Beds", "/admin/wards-beds", BedDouble, "R1", "admin"),
  item("facility-setup", "Facility Setup", "/admin/setup", Settings2, "R1", "admin"),
  item(
    "config-history",
    "Configuration History",
    "/admin/configuration/history",
    SlidersHorizontal,
    "R1",
    "admin",
  ),
  item(
    "registration-config",
    "Registration Config",
    "/admin/registration-config",
    UserRoundSearch,
    "R1",
    "patient_registry",
  ),
  item(
    "quality-profile",
    "Quality Profile",
    "/admin/quality-profile",
    ShieldCheck,
    "R3",
    "quality_os",
  ),
  item("abdm-qr", "ABDM / QR", "/admin/abdm/qr", QrCode, "R1", "abdm"),
  item("audit", "Audit", "/admin/audit", ScrollText, "R1", "audit"),

  // Platform & integration
  item("notifications", "Notifications", "/notifications", Bell, "R1", "platform"),
  item("abdm-exchange", "ABDM Exchange", "/abdm/exchange", ScanLine, "R6", "abdm"),
  item("integrations", "Integrations", "/admin/integrations", Plug, "R1", "integration"),
  item("tenants", "Platform Tenants", "/platform/tenants", UsersRound, "R1", "platform"),
];

export const NAV_GROUPS: readonly NavGroup[] = [
  { id: "main", label: "Main Menu", items: MAIN_ITEMS },
  { id: "settings", label: "Settings", items: SETTINGS_ITEMS },
] as const;

/** Every nav entry across all groups. */
export const NAV_ITEMS: readonly NavItem[] = NAV_GROUPS.flatMap((g) => g.items);

/** Total navigable entries — used by tests and the nav's aria summary. */
export function countEnabled(
  groups: readonly NavGroup[] = NAV_GROUPS,
): number {
  return groups.reduce(
    (total, group) =>
      total + group.items.filter((i) => i.availability === "enabled").length,
    0,
  );
}

/** True when the entry must render as a non-interactive placeholder. */
export function isNavItemDisabled(entry: NavItem): boolean {
  return entry.availability !== "enabled";
}

/**
 * Human-readable state text. design.md §23: never encode status by colour
 * alone, so every non-navigable entry carries an explicit label.
 */
export function navItemStateLabel(entry: NavItem): string | null {
  if (entry.availability === "enabled") return null;
  return entry.availability === "notEnabled" ? "Not enabled" : "Not available";
}

/** Full text for the `title` attribute, used by assistive tech on hover. */
export function navItemTitle(entry: NavItem): string {
  const state = navItemStateLabel(entry);
  return state ? `${entry.label} — ${state} (${entry.release})` : entry.label;
}

/** True when `path` is the active route (ignores query/hash). */
export function isNavItemActive(entry: NavItem, currentPath: string): boolean {
  if (entry.path === null) return false;
  if (entry.path === "/") return currentPath === "/";
  return currentPath === entry.path || currentPath.startsWith(`${entry.path}/`);
}