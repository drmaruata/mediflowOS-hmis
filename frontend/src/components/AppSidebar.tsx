/**
 * AppSidebar — persistent left navigation rail (Medicore restyle).
 *
 * Spec: design.md §5.3 (240px expanded / 72px collapsed, grouped
 * navigation), Medicore spec 2026-10-22 §2.3/§4.9 — nav-code chips replace
 * icons — and §4.2 (theme-scoped chrome), plus UI_UX_design §4.1/§12
 * (keyboard reachable, no colour-only state, accessible names).
 *
 * Colour note: the chrome is theme-scoped — `--shell-*` values flip between
 * `:root` and `.dark` — so every colour here derives from a token and no
 * white utility survives (the old navy rail painted white labels that go
 * invisible on the light Medicore rail; AppShell + CI guard against that).
 *
 * Status encoding (design.md §23 — never colour alone): unbuilt modules show
 * their release tag plus an explicit state word in the accessible name.
 */

import { NavLink } from "react-router-dom";

import {
  NAV_GROUPS,
  isNavItemDisabled,

  navItemTitle,
  type NavItem,
} from "@/lib/navigation";
import { cn } from "@/lib/utils";
import { useThemeStore, type ThemePreference } from "@/stores/themeStore";

export interface AppSidebarProps {
  /** Collapsed rail shows chips only (design.md §5.3, §17 tablet). */
  collapsed?: boolean;
  className?: string;
}

function NavEntry({
  entry,
  collapsed,
}: {
  entry: NavItem;
  collapsed: boolean;
}) {
  const disabled = isNavItemDisabled(entry);

  // The chip replaces the Lucide icon (Medicore identity, spec §4.9). It is
  // aria-hidden: it only duplicates the label, and hiding it keeps the
  // link's accessible name exactly "Dashboard" rather than "DB Dashboard".
  const chip = (
    <span
      aria-hidden="true"
      className={cn(
        "grid size-[26px] shrink-0 place-items-center rounded-md border font-mono text-[10px] font-medium tracking-[0.04em]",
        "border-shell-sidebar-border",
        disabled
          ? "text-shell-sidebar-foreground/60"
          : "text-shell-sidebar-foreground/80",
      )}
    >
      {entry.code}
    </span>
  );

  const content = (
    <>
      {chip}
      <span className={cn("truncate", collapsed && "sr-only")}>
        {entry.label}
      </span>
    </>
  );

  const baseClasses = cn(
    "flex h-9 items-center gap-2.5 rounded-lg px-2 text-sm transition-colors",
    // Focus ring must be visible on the rail, the hover fill and the
    // accent-soft active fill alike (design.md §23).
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-shell-sidebar-subtle",
    collapsed && "justify-center px-0",
  );

  if (disabled) {
    return (
      <span
        className={cn(
          baseClasses,
          // 60% alpha over the light rail measures ≈5.6:1 (barely lower over
          // the dark rail). At 50% it sat under the 4.5:1 normal-text floor,
          // and these labels are the only signal that a module exists but
          // is unbuilt.
          "cursor-not-allowed text-shell-sidebar-foreground/60",
        )}
        aria-disabled="true"
        title={navItemTitle(entry)}
      >
        {content}
        {/* Release tag = the build target; also the non-colour state signal. */}
        {!collapsed && (
          <span className="ml-auto shrink-0 font-mono text-[10px] font-medium text-shell-sidebar-subtle">
            {entry.release}
          </span>
        )}
      </span>
    );
  }

  return (
    <NavLink
      to={entry.path ?? "/"}
      end={entry.path === "/"}
      title={navItemTitle(entry)}
      className={({ isActive }) =>
        cn(
          baseClasses,
          "text-shell-sidebar-foreground/85 hover:bg-shell-sidebar-hover hover:text-shell-sidebar-foreground",
          // Active entry = the Medicore accent-soft fill with its dark-green
          // ink — the pair styles.unit.test pins at ≥4.5:1.
          isActive && "bg-shell-active font-semibold text-shell-active-foreground hover:bg-shell-active",
        )
      }
    >
      {content}
    </NavLink>
  );
}

function Group({
  label,
  items,
  collapsed,
}: {
  label: string;
  items: readonly NavItem[];
  collapsed: boolean;
}) {
  return (
    <div>
      {!collapsed && (
        <h2 className="px-2.5 pb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-shell-sidebar-subtle">
          {label}
        </h2>
      )}
      <ul className="flex flex-col gap-0.5">
        {items.map((entry) => (
          <li key={entry.id}>
            <NavEntry entry={entry} collapsed={collapsed} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Brand mark + wordmark; collapses to the mark alone on the 72px rail. */
function BrandBlock({ collapsed }: { collapsed: boolean }) {
  return (
    <div
      className={cn(
        "flex items-center gap-2.5 px-2 pt-2 pb-1",
        collapsed && "justify-center px-0",
      )}
    >
      <span
        aria-hidden="true"
        className="grid size-8 shrink-0 place-items-center rounded-[10px] bg-primary font-display text-sm font-bold text-primary-foreground"
      >
        M
      </span>
      {!collapsed && (
        <span className="flex min-w-0 flex-col leading-tight">
          <span className="truncate font-display text-[13px] font-bold uppercase tracking-[0.08em] text-shell-sidebar-foreground">
            Mediflow
          </span>
          <span className="truncate text-[10px] uppercase tracking-[0.08em] text-shell-sidebar-subtle">
            Hospital Information System
          </span>
        </span>
      )}
    </div>
  );
}

const THEME_OPTIONS: ReadonlyArray<{ value: ThemePreference; label: string }> = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

/**
 * Sidebar footer: the theme switcher moves here from the topbar (Medicore
 * spec §4.5). Three segments, not two: the store's `system` preference and
 * its OS-sync must stay reachable, or silent resolution would replace an
 * explicit user contract.
 */
function SidebarFooter() {
  const preference = useThemeStore((s) => s.preference);
  const setPreference = useThemeStore((s) => s.setPreference);

  return (
    <div className="mt-auto border-t border-shell-sidebar-border p-2 pt-2.5">
      <div
        role="group"
        aria-label="Theme selection"
        className="grid grid-cols-3 gap-0.5 rounded-lg border border-shell-sidebar-border bg-shell-sidebar-hover p-0.5"
      >
        {THEME_OPTIONS.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            aria-pressed={preference === value}
            onClick={() => setPreference(value)}
            className={cn(
              "rounded-md px-1 py-1.5 text-[13px] font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-shell-sidebar-subtle",
              preference === value
                ? "bg-shell-topbar text-shell-sidebar-foreground shadow-sm"
                : "text-shell-sidebar-subtle hover:text-shell-sidebar-foreground",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="mt-2 px-1 font-mono text-[10px] text-shell-sidebar-subtle">
        Mediflow OS · React 18 · Django 5.2
      </p>
    </div>
  );
}

export function AppSidebar({ collapsed = false, className }: AppSidebarProps) {
  return (
    <aside
      className={cn(
        "sticky top-16 z-30 hidden h-[calc(100svh-4rem)] shrink-0 overflow-y-auto",
        "border-r border-shell-sidebar-border bg-shell-sidebar text-shell-sidebar-foreground transition-[width] duration-150",
        "md:block",
        collapsed ? "w-[72px]" : "w-60",
        className,
      )}
      aria-label="Main navigation"
    >
      {/* Footer stays mounted when collapsed (CSS-hidden) so the switcher's
          state never remounts mid-session. */}
      <div className="flex h-full flex-col px-2 py-2">
        <BrandBlock collapsed={collapsed} />
        <nav className="mt-3 flex flex-col gap-4" aria-label="Primary">
          {NAV_GROUPS.map((group) => (
            <Group
              key={group.id}
              label={group.label}
              items={group.items}
              collapsed={collapsed}
            />
          ))}
        </nav>
        <div className={cn(collapsed && "hidden")}>
          <SidebarFooter />
        </div>
      </div>
    </aside>
  );
}

/**
 * Narrow-viewport drawer variant. design.md §17 collapses the sidebar on
 * tablet; below `md` the shell has no room, so navigation moves into an
 * overlay opened from the header. Same chip styling as the rail.
 */
export function AppSidebarDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 md:hidden">
      <button
        type="button"
        aria-label="Close navigation"
        onClick={onClose}
        className="absolute inset-0 bg-foreground/40"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Main navigation"
        className="absolute inset-y-0 left-0 w-72 overflow-y-auto bg-shell-sidebar p-2 text-shell-sidebar-foreground"
      >
        <BrandBlock collapsed={false} />
        <nav className="mt-3" aria-label="Primary">
          {NAV_GROUPS.map((group) => (
            <Group
              key={group.id}
              label={group.label}
              items={group.items}
              collapsed={false}
            />
          ))}
        </nav>
        {/* The theme control otherwise vanishes with the rail on md- and
            inside the drawer (review I1). */}
        <SidebarFooter />
      </div>
    </div>
  );
}
