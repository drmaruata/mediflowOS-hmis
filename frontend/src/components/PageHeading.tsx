/**
 * PageHeading — the single page header every route gets (Medicore restyle).
 *
 * Spec 2026-10-22 §4.8: the h1 resolves from the nav model — exact
 * `NavItem.path` match, else the longest `path + "/"` prefix, else the
 * title-cased first route segment. The breadcrumb links home on
 * non-dashboard routes; the date pill is a real `<time>` element (never the
 * mock's fake button); the module chip renders the nav code in the
 * single-accent scheme (the mock's ten per-module decorative colours are
 * dropped — ten tokens for zero information).
 *
 * The dashboard route keeps the h1 "Welcome back" with no breadcrumb and no
 * chip: AppShell's route test pins that heading, and the mock devotes the
 * dashboard header to the greeting itself. Screens drop their own h1s in
 * the sweep so exactly one h1 remains per route (design.md §23).
 */

import { Link, useLocation } from "react-router-dom";

import { NAV_ITEMS, type NavItem } from "@/lib/navigation";
import { cn } from "@/lib/utils";

interface Heading {
  title: string;
  code: string | null;
  isDashboard: boolean;
}

function titleFor(pathname: string): Heading {
  const exact = NAV_ITEMS.find((entry) => entry.path === pathname);
  // Longest prefix wins: /patients/123 names the registry, not the deepest
  // tote; sorting by path length makes the intent local and obvious.
  const prefix = NAV_ITEMS.filter(
    (entry) =>
      entry.path !== null &&
      pathname.startsWith(`${entry.path}/`) &&
      pathname !== `${entry.path}/`,
  ).sort((a, b) => (b.path?.length ?? 0) - (a.path?.length ?? 0))[0];

  const entry: NavItem | undefined = exact ?? prefix;
  if (entry) {
    const isDashboard = entry.id === "dashboard";
    return {
      title: isDashboard ? "Welcome back" : entry.label,
      code: isDashboard ? null : entry.code,
      isDashboard,
    };
  }

  // Nothing in the nav model matches (e.g. a role screen under /admin):
  // derive a readable title from the first segment so no route header is
  // missing its h1.
  const segments = pathname.split("/").filter(Boolean);
  const title = segments[0]
    .replace(/-/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
  return { title: title || "Mediflow", code: null, isDashboard: false };
}

export function PageHeading() {
  const { pathname } = useLocation();
  const { title, code, isDashboard } = titleFor(pathname);

  const now = new Date();
  // Machine-readable dt attribute + locale display; the pill is real state,
  // not the mock's decorative control (spec §4.12).
  const iso = now.toISOString().slice(0, 10);
  const dateText = now.toLocaleDateString("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
      <div className="min-w-0">
        {!isDashboard && (
          <nav
            aria-label="Breadcrumb"
            className="text-[13px] text-muted-foreground"
          >
            <Link
              to="/dashboard"
              className="underline-offset-2 hover:text-foreground hover:underline"
            >
              Dashboard
            </Link>
            <span aria-hidden="true"> / </span>
            <span aria-current="page">{title}</span>
          </nav>
        )}
        <h1 className="font-display font-bold tracking-tight text-foreground text-[clamp(22px,2vw,28px)]">
          {title}
        </h1>
      </div>
      <div className="flex items-center gap-1.5">
        {code && (
          <span
            aria-hidden="true"
            className="rounded-md bg-brand-accent-soft px-2 py-1 font-mono text-[10px] font-semibold text-brand-accent-ink"
          >
            {code}
          </span>
        )}
        <time
          dateTime={iso}
          className={cn(
            "rounded-md border border-border bg-shell-sidebar-hover px-2 py-1",
            "text-[13px] text-shell-sidebar-foreground/80",
          )}
        >
          {dateText}
        </time>
      </div>
    </div>
  );
}
