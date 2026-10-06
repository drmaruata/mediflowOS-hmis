/**
 * AppHeader — global application top bar.
 *
 * Spec: design.md §5.2 (64px height; left = logo + tenant/facility
 * selector, global search, right = notification bell, connection state,
 * user menu; tenant context must stay visible after scrolling),
 * §2.3A (`#153047` top bar), UI_UX_design §4.2, §6.3 (Ctrl+K palette),
 * §12 (every icon-only control has an accessible name).
 *
 * Context selectors are real `<select>` elements rather than a tooltip or
 * avatar menu: design.md §5.2 forbids hiding facility/department context
 * inside an avatar only.
 */

import { Activity, Bell, Menu, PanelLeftClose, PanelLeftOpen, Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ThemeToggle } from "@/components/ThemeToggle";

export interface AppHeaderProps {
  /** Live-data indicator state (design.md §8.14). */
  isLive?: boolean;
  /** Hide the search field on very narrow viewports. */
  isCompact?: boolean;
  /** Rail collapsed state; drives the toggle's accessible name. */
  collapsed?: boolean;
  onOpenNav?: () => void;
  onToggleCollapsed?: () => void;
}

export function AppHeader({
  isLive = false,
  isCompact = false,
  collapsed = false,
  onOpenNav,
  onToggleCollapsed,
}: AppHeaderProps) {
  return (
    <header className="sticky top-0 z-40 flex h-16 items-center gap-3 bg-shell-topbar px-4 text-white md:px-6">
      {/* Compact-viewport nav trigger */}
      <Button
        variant="ghost"
        size="icon"
        onClick={onOpenNav}
        disabled={!onOpenNav}
        aria-label="Open navigation"
        className="text-white hover:bg-white/10 hover:text-white md:hidden"
      >
        <Menu className="size-5" aria-hidden="true" />
      </Button>

      {/* Desktop rail collapse toggle */}
      <Button
        variant="ghost"
        size="icon"
        onClick={onToggleCollapsed}
        disabled={!onToggleCollapsed}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        aria-expanded={!collapsed}
        className="hidden text-white hover:bg-white/10 hover:text-white md:inline-flex"
      >
        {collapsed ? (
          <PanelLeftOpen className="size-5" aria-hidden="true" />
        ) : (
          <PanelLeftClose className="size-5" aria-hidden="true" />
        )}
      </Button>

      {/* Logo + wordmark (design.md §2.4) */}
      <div className="flex items-center gap-2.5">
        <div className="flex size-9 items-center justify-center rounded-lg bg-primary">
          <Activity className="size-5 text-primary-foreground" aria-hidden="true" />
        </div>
        <span className="hidden text-lg font-semibold tracking-tight md:inline">
          Mediflow OS
        </span>
      </div>

      {/*
        Tenant / facility / department context. Must remain visible after
        scrolling (design.md §5.2) — hence a plain header control, not a
        hover menu. Options are placeholders until tenant config is wired;
        aria-labels keep them distinguishable to screen readers.
      */}
      <div className="hidden items-center gap-2 lg:flex">
        <label className="sr-only" htmlFor="header-tenant">
          Tenant
        </label>
        <select
          id="header-tenant"
          className="h-9 rounded-md border border-white/20 bg-white/10 px-2 text-sm text-white hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
          defaultValue=""
        >
          <option value="" className="text-foreground">
            Select tenant
          </option>
        </select>

        <label className="sr-only" htmlFor="header-facility">
          Facility
        </label>
        <select
          id="header-facility"
          className="h-9 rounded-md border border-white/20 bg-white/10 px-2 text-sm text-white hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
          defaultValue=""
        >
          <option value="" className="text-foreground">
            Select facility
          </option>
        </select>
      </div>

      {/* Global patient search — search-first per design.md §8.15 */}
      <div className="ml-auto flex min-w-0 flex-1 items-center justify-end gap-2 md:ml-4 md:justify-start">
        {!isCompact && (
          <div className="relative hidden min-w-0 flex-1 max-w-md md:block">
            <label className="sr-only" htmlFor="global-patient-search">
              Search patient by UHID, name, phone or ABHA
            </label>
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-white/60"
              aria-hidden="true"
            />
            <Input
              id="global-patient-search"
              type="search"
              placeholder="Search patient by UHID, name, phone, ABHA…"
              className="h-9 border-white/20 bg-white/10 pl-8 pr-14 text-white placeholder:text-white/60 focus-visible:ring-white"
            />
            {/* Keyboard hint, design.md §8.15 */}
            <kbd className="pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 rounded border border-white/25 bg-white/10 px-1.5 py-0.5 font-mono text-[10px] text-white/80 lg:block">
              Ctrl K
            </kbd>
          </div>
        )}

        <Badge
          variant="outline"
          className={
            isLive
              ? "shrink-0 border-transparent bg-green-600 text-white hover:bg-green-600"
              : "shrink-0 border-white/25 bg-white/10 text-white/80 hover:bg-white/10"
          }
        >
          {isLive ? "Live Data" : "Demo data"}
        </Badge>

        <Button
          variant="ghost"
          size="icon"
          aria-label="Notifications"
          className="text-white hover:bg-white/10 hover:text-white"
        >
          <Bell className="size-5" aria-hidden="true" />
        </Button>

        {/* Theme control (design.md §16) */}
        <ThemeToggle onDarkSurface />

        {/* User menu placeholder — identity disclosure belongs here once the
            auth store exposes the signed-in user (UI-003). */}
        <Button
          variant="ghost"
          size="icon"
          aria-label="User menu"
          className="text-white hover:bg-white/10 hover:text-white"
        >
          <span
            aria-hidden="true"
            className="flex size-7 items-center justify-center rounded-full bg-white/15 text-xs font-semibold"
          >
            —
          </span>
        </Button>
      </div>
    </header>
  );
}