/**
 * DashboardView — the dashboard on the Medicore modern layout (spec
 * 2026-10-22 §2.6, §4.6-§4.12).
 *
 * Panels: OPD hero + two bordered minis, a fixture-driven dual-series bar
 * chart with a working range select, a working calendar, a searchable
 * new-patients table, and a module strip whose unbuilt modules are honest
 * disabled buttons carrying their release state.
 *
 * The former KPI/admissions/donut bundle died with the chart-library
 * removal (README "UI system migration"); the health band moved to
 * AppHeader (Task 4), so this view fetches nothing — fixtures only, per
 * dashboard.unit.test.ts. No screen h1: PageHeading owns the route heading.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  NAV_ITEMS,
  isNavItemDisabled,
  navItemStateLabel,
  navItemTitle,
} from "@/lib/navigation";
import { cn } from "@/lib/utils";
import {
  calendarMonthCells,
  fixtureCalendarEvents,
  fixtureMinis,
  fixtureNewPatients,
  fixtureOpdVolume,
  fixturePatientsTotal,
} from "./dashboard.fixture";

export interface DashboardViewProps {
  /** Swaps the hero's data-source pill copy (design.md §8.14). */
  isLive?: boolean;
}

function initials(name: string): string {
  return name
    .split(" ")
    .map((word) => word.charAt(0))
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function OpdHero({ isLive }: { isLive: boolean }) {
  // Series `a` = new registrations; the hero reveals today's count from the
  // same data the chart shows, so the two can never disagree.
  const registrations = fixtureOpdVolume.reduce((sum, row) => sum + row.a, 0);

  return (
    <article
      aria-label="OPD today"
      className="grid grid-cols-[auto_1fr] items-center gap-3 rounded-xl bg-primary p-5 text-primary-foreground sm:col-span-full lg:col-span-1"
    >
      <span
        aria-hidden="true"
        className="grid size-9 place-items-center rounded-lg bg-background/40 font-display text-sm font-bold"
      >
        OPD
      </span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <strong className="font-display text-3xl font-bold tracking-tight">
            {registrations.toLocaleString("en-IN")}
          </strong>
          <span className="text-xs text-primary-foreground/80">
            OPD registrations today
          </span>
        </div>
        <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-primary-foreground/80">
          <span aria-hidden="true">▲</span>
          <span>8% vs yesterday</span>
          <span className="inline-flex items-center rounded-md bg-background/40 px-2 py-0.5 font-semibold">
            {isLive ? "Live data" : "Demo data"}
          </span>
        </p>
      </div>
    </article>
  );
}

const OPD_RANGES = [
  { value: "week", label: "This week" },
  { value: "3d", label: "Last 3 days" },
] as const;

type OpdRange = (typeof OPD_RANGES)[number]["value"];

function TotalPatientsChart() {
  const [range, setRange] = useState<OpdRange>("week");
  const rows = range === "week" ? fixtureOpdVolume : fixtureOpdVolume.slice(-3);
  // Heights are relative to the visible window so each range fills the plot.
  const max = Math.max(...rows.flatMap((row) => [row.a, row.b]));

  return (
    <section
      aria-label="Total patients trend"
      className="rounded-2xl border border-border bg-card p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm text-muted-foreground">Total patients</p>
          <strong className="font-display text-[22px] font-bold tracking-tight text-foreground">
            {fixturePatientsTotal.toLocaleString("en-IN")}
          </strong>
        </div>
        <select
          aria-label="Chart range"
          value={range}
          onChange={(event) => {
            // No cast: resolve the option so an unexpected value is a no-op,
            // not a corrupted state.
            const option = OPD_RANGES.find(
              (candidate) => candidate.value === event.target.value,
            );
            if (option) setRange(option.value);
          }}
          className="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {OPD_RANGES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <p className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <span
            aria-hidden="true"
            className="size-2 rounded-full bg-brand-accent"
          />
          New
        </span>
        <span className="flex items-center gap-1">
          <span
            aria-hidden="true"
            className="size-2 rounded-full bg-brand-accent/40"
          />
          Returning
        </span>
      </p>
      {/* Columns stretch to the plot height; each bar's % height resolves
          against the flex-1 plot box (a content-sized parent gives 0). */}
      <div className="mt-3 flex h-[150px] gap-2 border-b border-border">
        {rows.map((row) => (
          <div key={row.day} className="flex flex-1 flex-col">
            <div
              role="img"
              aria-label={`${row.day}: ${row.a} new, ${row.b} returning`}
              className="flex w-full flex-1 items-end justify-center gap-1"
            >
              <span
                className="w-2.5 rounded-t bg-brand-accent"
                style={{ height: `${(row.a / max) * 100}%` }}
              />
              <span
                className="w-2.5 rounded-t bg-brand-accent/40"
                style={{ height: `${(row.b / max) * 100}%` }}
              />
            </div>
            <span className="mt-1 font-mono text-[10px] text-muted-foreground">
              {row.day.split(" ")[0]}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

const WEEKDAY_LETTERS = ["S", "M", "T", "W", "T", "F", "S"] as const;

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function CalendarCard() {
  const [selected, setSelected] = useState(() => new Date());
  const cells = calendarMonthCells(selected);
  const monthLabel = selected.toLocaleDateString("en-IN", {
    month: "long",
    year: "numeric",
  });

  return (
    <section
      aria-label="Calendar"
      className="rounded-2xl border border-border bg-card p-5"
    >
      <div className="flex items-center justify-between">
        <h2 className="font-display text-sm font-semibold text-foreground">
          {monthLabel}
        </h2>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setSelected(new Date())}
        >
          Today
        </Button>
      </div>
      <div className="mt-3 grid grid-cols-7 text-center font-mono text-[10px] text-muted-foreground">
        {WEEKDAY_LETTERS.map((letter, index) => (
          <span key={`${letter}-${index}`}>{letter}</span>
        ))}
      </div>
      <div className="mt-1 grid grid-cols-7 gap-0.5">
        {cells.map((cell, index) =>
          cell === null ? (
            <span key={`blank-${index}`} />
          ) : (
            <button
              key={cell.toISOString()}
              type="button"
              aria-pressed={sameDay(cell, selected)}
              onClick={() => setSelected(cell)}
              className={cn(
                "grid h-7 place-items-center rounded-md text-xs text-foreground",
                "hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                sameDay(cell, selected) &&
                  "bg-primary font-semibold text-primary-foreground",
              )}
            >
              {cell.getDate()}
            </button>
          ),
        )}
      </div>
      <ul className="mt-3 flex flex-col gap-1.5 border-t border-border pt-3">
        {fixtureCalendarEvents.map((event) => (
          <li
            key={event.title}
            className="flex items-center gap-2 text-xs text-muted-foreground"
          >
            <span
              aria-hidden="true"
              className="size-1.5 shrink-0 rounded-full bg-brand-accent"
            />
            <span className="font-mono">{event.time}</span>
            <span className="truncate">{event.title}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function NewPatientsCard() {
  const [query, setQuery] = useState("");
  const needle = query.trim().toLocaleLowerCase();
  // Search narrows the fixture rows by UHID or name — real state, no mock
  // pretending to filter (spec §4.12: every control on the screen works).
  const rows = fixtureNewPatients.filter(
    (row) =>
      needle === "" ||
      row.uhid.toLocaleLowerCase().includes(needle) ||
      row.name.toLocaleLowerCase().includes(needle),
  );

  return (
    <section
      aria-label="New patients"
      className="overflow-hidden rounded-2xl border border-border bg-card"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 p-5 pb-4">
        <div>
          <h2 className="font-display text-[15px] font-semibold text-foreground">
            New patients
          </h2>
          <p className="text-xs text-muted-foreground">Registered today</p>
        </div>
        <div className="flex items-center gap-2">
          <Input
            aria-label="Search patients"
            placeholder="Search UHID or name…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="h-8 w-44 text-foreground"
          />
          <Button asChild variant="outline" size="sm">
            <Link to="/patients">View all</Link>
          </Button>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-sm">
          <thead>
            <tr>
              {["UHID", "Patient", "Department", "Registered", "Status"].map(
                (heading) => (
                  <th
                    key={heading}
                    scope="col"
                    className="border-y border-border bg-muted px-3.5 py-2.5 text-left text-xs font-medium text-muted-foreground"
                  >
                    {heading}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.uhid} className="hover:bg-muted/50">
                <td className="border-b border-border px-3.5 py-2.5 font-mono text-foreground">
                  {row.uhid}
                </td>
                <td className="border-b border-border px-3.5 py-2.5">
                  <span className="flex items-center gap-2">
                    <span
                      aria-hidden="true"
                      className="grid size-6 shrink-0 place-items-center rounded-md bg-brand-accent-soft text-[10px] font-semibold text-brand-accent-ink"
                    >
                      {initials(row.name)}
                    </span>
                    <span className="font-medium text-foreground">
                      {row.name}
                    </span>
                  </span>
                </td>
                <td className="border-b border-border px-3.5 py-2.5 text-muted-foreground">
                  {row.department}
                </td>
                <td className="border-b border-border px-3.5 py-2.5 font-mono text-muted-foreground">
                  {row.time}
                </td>
                <td className="border-b border-border px-3.5 py-2.5">
                  {/* Word carries the meaning (design.md §23); the tint is
                      only the finish. Pending uses the neutral secondary pair. */}
                  <span
                    className={cn(
                      "inline-flex rounded px-2 py-1 text-xs font-medium",
                      row.status === "confirmed"
                        ? "bg-brand-accent-soft text-brand-accent-ink"
                        : "bg-secondary text-secondary-foreground",
                    )}
                  >
                    {row.status === "confirmed" ? "Confirmed" : "Pending"}
                  </span>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td
                  colSpan={5}
                  className="px-3.5 py-3 text-sm text-muted-foreground"
                >
                  No patients match “{query}”.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/**
 * Strip ids mirror the rail's bounded contexts; availability comes from the
 * nav model (AGENTS.md §5: unbuilt modules are disabled, never dead links).
 */
const STRIP_IDS = [
  "opd",
  "ipd",
  "emergency",
  "ot",
  "icu",
  "lis",
  "ris",
  "pharmacy",
  "insurance",
  "emr",
] as const;

const stripBase = "flex items-center gap-2 rounded-xl border p-2.5 text-left";

function ModuleStrip() {
  return (
    <div
      role="group"
      aria-label="Module overview"
      className="grid grid-cols-2 gap-2 md:grid-cols-5"
    >
      {STRIP_IDS.map((id) => {
        const entry = NAV_ITEMS.find((item) => item.id === id);
        if (!entry) return null;
        const chip = (
          <span
            aria-hidden="true"
            className="grid size-7 shrink-0 place-items-center rounded-md bg-brand-accent-soft font-mono text-[10px] font-semibold text-brand-accent-ink"
          >
            {entry.code}
          </span>
        );
        const label = (
          <strong className="truncate text-xs font-semibold">
            {entry.label}
          </strong>
        );
        if (isNavItemDisabled(entry)) {
          return (
            <button
              key={id}
              type="button"
              disabled
              title={navItemTitle(entry)}
              className={cn(
                stripBase,
                "cursor-not-allowed border-border bg-card text-muted-foreground opacity-60",
              )}
            >
              {chip}
              {label}
              <span className="sr-only">{navItemStateLabel(entry)}</span>
            </button>
          );
        }
        return (
          <Link
            key={id}
            to={entry.path ?? "/"}
            title={navItemTitle(entry)}
            className={cn(
              stripBase,
              "border-border bg-card text-card-foreground hover:border-ring",
            )}
          >
            {chip}
            {label}
          </Link>
        );
      })}
    </div>
  );
}

export default function DashboardView({
  isLive = false,
}: DashboardViewProps = {}) {
  return (
    <div className="grid gap-4">
      {/* Mock proportions: hero column ~0.8fr, chart ~1.65fr, calendar 1fr. */}
      <div className="grid gap-3 lg:grid-cols-[minmax(200px,0.8fr)_minmax(340px,1.65fr)_minmax(240px,1fr)]">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
          <OpdHero isLive={isLive} />
          {fixtureMinis.map((mini) => (
            <article
              key={mini.label}
              aria-label={mini.label}
              className="rounded-xl border border-border bg-background p-4 text-center"
            >
              <strong className="font-display text-2xl font-bold text-brand-accent-ink">
                {mini.value}
              </strong>
              <p className="text-sm text-muted-foreground">{mini.label}</p>
            </article>
          ))}
        </div>
        <TotalPatientsChart />
        <CalendarCard />
      </div>
      <NewPatientsCard />
      <ModuleStrip />
    </div>
  );
}
