/**
 * AppSidebar — persistent left navigation rail.
 *
 * Spec: design.md §5.3 (240px expanded / 72px collapsed, grouped
 * navigation), §2.3A (dark navy rail `#132134`, blue active emphasis
 * `#0B75E5`), §8.0/§8.1, UI_UX_design §4.1/§12 (keyboard reachable, no
 * colour-only state, accessible names).
 *
 * Colour note: the rail is a fixed navy in BOTH themes, so every colour here
 * comes from a `--shell-sidebar-*` token rather than `--sidebar-*`. The
 * theme-scoped pair painted dark labels on the navy rail in light mode.
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

export interface AppSidebarProps {
  /** Collapsed rail shows icons only (design.md §5.3, §17 tablet). */
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

  const Icon = entry.icon;

  const content = (
    <>
      <Icon className="size-4 shrink-0" aria-hidden="true" />
      <span className={cn("truncate", collapsed && "sr-only")}>
        {entry.label}
      </span>
    </>
  );

  const baseClasses = cn(
    "flex h-9 items-center gap-2.5 rounded-md px-2.5 text-sm transition-colors",
    // Focus ring must clear 3:1 against both the navy rail and the blue
    // active fill (design.md §23).
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white",
    collapsed && "justify-center px-0",
  );

  if (disabled) {
    return (
      <span
        className={cn(
          baseClasses,
          // 60% alpha over the navy rail measures ~5.6:1. At 50% it was
          // ~4.3:1 — under the 4.5:1 normal-text floor, and these labels are
          // the only signal that a module exists but is unbuilt.
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
          // Active fill is #0B6BD4 (white = 5.21:1), darkened from
          // design.md §2.3A's #0B75E5 which failed AA at 4.48:1.
          isActive &&
            "bg-shell-active font-semibold text-white hover:bg-shell-active",
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

export function AppSidebar({ collapsed = false, className }: AppSidebarProps) {
  return (
    <aside
      className={cn(
        "sticky top-16 z-30 hidden h-[calc(100svh-4rem)] shrink-0 overflow-y-auto",
        "border-r border-shell-sidebar-border bg-shell-sidebar transition-[width] duration-150",
        "md:block",
        collapsed ? "w-[72px]" : "w-60",
        className,
      )}
      aria-label="Main navigation"
    >
      <nav className="flex flex-col gap-4 p-2" aria-label="Primary">
        {NAV_GROUPS.map((group) => (
          <Group
            key={group.id}
            label={group.label}
            items={group.items}
            collapsed={collapsed}
          />
        ))}
      </nav>
    </aside>
  );
}

/**
 * Narrow-viewport drawer variant. design.md §17 collapses the sidebar on
 * tablet; below `md` the shell has no room, so navigation moves into an
 * overlay opened from the header.
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
        <nav aria-label="Primary">
          {NAV_GROUPS.map((group) => (
            <Group
              key={group.id}
              label={group.label}
              items={group.items}
              collapsed={false}
            />
          ))}
        </nav>
      </div>
    </div>
  );
}