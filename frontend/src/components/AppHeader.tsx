/**
 * AppHeader — global application top bar (Medicore restyle).
 *
 * Spec: design.md §5.2 (64px height; left = logo + tenant/facility
 * selector, global search, right = notification bell, connection state,
 * user menu; tenant context must stay visible after scrolling),
 * Medicore spec 2026-10-22 §2.4/§4.2 (theme-scoped light chrome — no white
 * utilities survive from the old fixed-navy top bar), UI_UX_design §4.2,
 * §6.3 (Ctrl+K palette), §12 (every icon-only control has an accessible
 * name).
 *
 * The health probe chip (spec §4.6) is the real connection state — the
 * dashboard band's query moved here; the mock's hardcoded "Operational"
 * string is replaced by query data (see lib/health).
 *
 * Context selectors are real `<select>` elements rather than a tooltip or
 * avatar menu: design.md §5.2 forbids hiding facility/department context
 * inside an avatar only.
 */

import { Activity, Bell, LogOut, Menu, PanelLeftClose, PanelLeftOpen, Search } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { fetchHealth } from "@/lib/health";
import { cn } from "@/lib/utils";
import { useSession } from "@/lib/session";
import { useAuthStore } from "@/stores/authStore";
import { logout } from "@/modules/auth/auth.api";

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

/**
 * Topbar ghost controls. The old white-on-navy utilities die here: the
 * chrome is theme-scoped, so every surface/text belongs to a shell token —
 * hover fill is the rail hover token, working on both light and dark topbars.
 */
const TOPBAR_ICON_BUTTON = "text-shell-topbar-foreground hover:bg-shell-sidebar-hover hover:text-shell-topbar-foreground focus-visible:ring-shell-sidebar-subtle";

export function AppHeader({
  isLive = false,
  isCompact = false,
  collapsed = false,
  onOpenNav,
  onToggleCollapsed,
}: AppHeaderProps) {
  const queryClient = useQueryClient();
  const session = useSession();
  const username = session.data?.username;
  const initial = username ? username.charAt(0).toUpperCase() : null;

  // Real connection state (spec §4.6): moved verbatim from the dashboard band.
  const { data: health, isLoading } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    retry: false,
    refetchInterval: 30_000,
    staleTime: 25_000,
  });

  const healthWord = isLoading
    ? "Checking…"
    : health?.status === "ok"
      ? "Operational"
      : health?.status === "degraded"
        ? "Degraded"
        : "API unreachable";
  const healthDotClass = isLoading
    ? "animate-pulse bg-tone-neutral"
    : health?.status === "ok"
      ? "bg-tone-positive"
      : health?.status === "degraded"
        ? "animate-pulse bg-tone-neutral"
        : "animate-pulse bg-tone-negative";

  // Contractual order (UI-001): blacklist first, clear second — a network
  // failure must not trap a leaving user in the app, but is never silent.
  const handleSignOut = async () => {
    const { refreshToken, clearTokens } = useAuthStore.getState();
    try {
      if (refreshToken) {
        await logout(refreshToken);
      }
    } catch (err) {
      console.warn(
        "mediflow: token blacklisting failed during sign-out; clearing the local session anyway",
        err,
      );
    }
    clearTokens();
    queryClient.removeQueries({ queryKey: ["auth"] });
  };

  return (
    <header className="sticky top-0 z-40 flex h-16 items-center gap-3 border-b border-shell-sidebar-border bg-shell-topbar px-4 text-shell-topbar-foreground md:px-6">
      {/* Compact-viewport nav trigger */}
      <Button
        variant="ghost"
        size="icon"
        onClick={onOpenNav}
        disabled={!onOpenNav}
        aria-label="Open navigation"
        className={cn(TOPBAR_ICON_BUTTON, "md:hidden")}
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
        className={cn(TOPBAR_ICON_BUTTON, "hidden md:inline-flex")}
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
        <span className="hidden font-display text-lg font-semibold tracking-tight md:inline">
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
          className="h-9 rounded-md border border-shell-sidebar-border bg-shell-sidebar-hover px-2 text-sm text-shell-topbar-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-shell-sidebar-subtle"
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
          className="h-9 rounded-md border border-shell-sidebar-border bg-shell-sidebar-hover px-2 text-sm text-shell-topbar-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-shell-sidebar-subtle"
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
              className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              id="global-patient-search"
              type="search"
              placeholder="Search patient by UHID, name, phone, ABHA…"
              className="h-9 border-border bg-surface-subtle pl-8 pr-14 text-foreground placeholder:text-muted-foreground focus-visible:ring-ring"
            />
            {/* Keyboard hint, design.md §8.15 */}
            <kbd className="pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 rounded border border-border bg-shell-sidebar-hover px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground lg:block">
              Ctrl K
            </kbd>
          </div>
        )}

        {/* Right-side cluster (mock .topbar-actions): ml-auto pins it to the
            header's far edge so the bar spans the full shell width. */}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {/* Real connection state — a word carries meaning; colour only decorates
              it (design.md §23). The mock's hardcoded chip is replaced by query
              state (Medicore spec §4.6). */}
          <p
            role="status"
            aria-live="polite"
            className="hidden items-center gap-1.5 rounded-lg border border-border bg-shell-sidebar-hover px-2.5 py-1.5 text-xs text-shell-sidebar-subtle sm:flex"
          >
            <span
              aria-hidden="true"
              className={cn("size-2 shrink-0 rounded-full", healthDotClass)}
            />
            <span className="font-medium text-shell-topbar-foreground">{healthWord}</span>
          </p>

          {/*
            Live/Demo badge as a soft accent fill: brand-accent-soft +
            brand-accent-ink composites on both topbars (dark green-on-bright
            text would fail AA against the dark-theme bright green).
          */}
          <Badge
            variant="outline"
            className={
              isLive
                ? "shrink-0 border-ring bg-brand-accent-soft text-brand-accent-ink hover:bg-brand-accent-soft"
                : "shrink-0 border-border bg-shell-sidebar-hover text-shell-sidebar-subtle hover:bg-shell-sidebar-hover"
            }
          >
            {isLive ? "Live Data" : "Demo data"}
          </Badge>

          <Button
            variant="ghost"
            size="icon"
            aria-label="Notifications"
            className={TOPBAR_ICON_BUTTON}
          >
            <Bell className="size-5" aria-hidden="true" />
          </Button>

          {/* Theme control moved to the sidebar footer (Medicore spec §4.5) —
              single control, replacing the retired ThemeToggle dropdown. */}

          {/* User menu — session identity disclosure and sign-out (UI-001);
              the full profile card stays scoped to UI-003. */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                aria-label="User menu"
                className={TOPBAR_ICON_BUTTON}
              >
                <span
                  aria-hidden="true"
                  className="flex size-7 items-center justify-center rounded-full bg-foreground/10 text-xs font-semibold text-shell-topbar-foreground"
                >
                  {initial ?? "—"}
                </span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel className="flex flex-col gap-0.5">
                <span className="font-medium">{username ?? "Signed in"}</span>
                {session.data?.role && (
                  <span className="text-xs font-normal text-muted-foreground">
                    {session.data.role}
                  </span>
                )}
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                aria-label="Sign out"
                onSelect={() => void handleSignOut()}
              >
                <LogOut className="size-4" aria-hidden="true" />
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  );
}
