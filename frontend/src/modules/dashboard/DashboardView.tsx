/**
 * DashboardView — executive/operational dashboard (◪ [2026-10-02]).
 *
 * Spec: UI_UX_design.md §9 Quality home + §7 R1 screens, and design.md §8-§8.15
 * 1536×1024 reference composition: 6 KPI cards, 3-panel analytics row,
 * OT schedule, Critical Alerts, Admissions/Discharges, Patient Flow Funnel,
 * Department Performance. Only src/App.tsx and src/styles/index.css may change
 * outside src/modules/dashboard/ (◪ file-boundary rule).
 *
 * Data: synthetic fixture (dashboard.fixture.ts) with header "Demo data" and
 * prop-driven Live Data pill. Live API wiring swaps in via props later.
 * Charts: inline SVG only — donut via stroke-dasharray arcs, bars/funnel via
 * SVG primitives (◪ default charting approach). No chart library dependency.
 */

import { useQuery } from "@tanstack/react-query";
import {
  Users,
  BedDouble,
  FlaskConical,
  Activity,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  FileWarning,
  Stethoscope,
  Clock3,
} from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchHealth } from "@/lib/health";
import {
  fixtureKpis,
  fixtureBedOccupancy,
  fixtureOpdVolume,
  fixtureEmergencyAcuity,
  fixtureEmergencyFlow,
  fixtureOtSchedule,
  fixtureAlerts,
  fixtureAdmissions,
  fixtureFunnel,
  fixtureDepartments,
} from "./dashboard.fixture";

// ── small inline SVG helpers ──────────────────────────────────────────

function DonutChart({
  segments,
  label,
  centerLabel,
  centerSub,
  size = 140,
  strokeWidth = 16,
}: {
  segments: Array<{ value: number; color: string; name: string }>;
  label: string;
  centerLabel: string;
  centerSub?: string;
  size?: number;
  strokeWidth?: number;
}) {
  const total = segments.reduce((s, seg) => s + seg.value, 0) || 1;
  const r = (size - strokeWidth) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const C = 2 * Math.PI * r;
  let acc = 0;

  return (
    <div className="flex items-center gap-5">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label} className="shrink-0">
        <circle cx={cx} cy={cy} r={r} fill="none" strokeWidth={strokeWidth} stroke="hsl(var(--muted))" />
        {segments.map((seg) => {
          const dash = (seg.value / total) * C;
          const offset = (acc / total) * C;
          acc += seg.value;
          return (
            <circle
              key={seg.name}
              cx={cx}
              cy={cy}
              r={r}
              fill="none"
              strokeWidth={strokeWidth}
              stroke={seg.color}
              strokeDasharray={`${dash} ${C - dash}`}
              strokeDashoffset={-offset + C * 0.25}
              strokeLinecap="butt"
            />
          );
        })}
        <text x={cx} y={cy - 2} textAnchor="middle" className="fill-foreground font-bold" fontSize={size * 0.14}>
          {centerLabel}
        </text>
        {centerSub && (
          <text x={cx} y={cy + 12} textAnchor="middle" className="fill-muted-foreground" fontSize={size * 0.075}>
            {centerSub}
          </text>
        )}
      </svg>
      <ul className="flex flex-col gap-1.5">
        {segments.map((seg) => (
          <li key={seg.name} className="flex items-center gap-2 text-sm">
            <span className="inline-block size-2.5 rounded-sm" style={{ backgroundColor: seg.color }} aria-hidden="true" />
            <span className="text-muted-foreground">{seg.name}</span>
            <span className="ml-2 font-medium">{seg.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Sparkline({ values, color = "hsl(174 83% 30%)" }: { values: number[]; color?: string }) {
  const w = 96;
  const h = 28;
  const pad = 2;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  const step = (w - pad * 2) / (values.length - 1);
  const points = values
    .map((v, i) => {
      const x = pad + i * step;
      const y = h - pad - ((v - min) / range) * (h - pad * 2);
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Trend sparkline" className="shrink-0">
      <polyline fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" points={points} />
    </svg>
  );
}

function GroupedBars({ data }: { data: Array<{ day: string; a: number; b: number }> }) {
  const W = 360;
  const H = 180;
  const padL = 28;
  const padR = 8;
  const padT = 8;
  const padB = 28;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const max = Math.max(...data.flatMap((d) => [d.a, d.b])) * 1.1;
  const n = data.length;
  const groupW = plotW / n;
  const barW = Math.min(16, groupW * 0.3);
  const gap = 4;

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="OPD volume grouped bars, last 7 days" className="w-full">
      {/* grid lines */}
      {[0, 0.25, 0.5, 0.75, 1].map((t) => {
        const y = padT + plotH * (1 - t);
        const v = Math.round(max * t);
        return (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={y} y2={y} stroke="hsl(var(--border))" strokeWidth={0.7} />
            <text x={padL - 4} y={y + 3} textAnchor="end" fontSize={8} fill="hsl(var(--muted-foreground))">
              {v}
            </text>
          </g>
        );
      })}
      {data.map((d, i) => {
        const gx = padL + i * groupW + (groupW - (barW * 2 + gap)) / 2;
        const ha = (d.a / max) * plotH;
        const hb = (d.b / max) * plotH;
        return (
          <g key={d.day}>
            <rect x={gx} y={padT + plotH - ha} width={barW} height={ha} rx={2} fill="hsl(174 83% 30%)" />
            <rect x={gx + barW + gap} y={padT + plotH - hb} width={barW} height={hb} rx={2} fill="hsl(200 70% 55%)" />
            <text x={gx + barW + gap / 2} y={H - 8} textAnchor="middle" fontSize={8} fill="hsl(var(--muted-foreground))">
              {d.day}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function FunnelChart({ data }: { data: Array<{ stage: string; count: number; pct: number }> }) {
  const W = 260;
  const rowH = 34;
  const gap = 6;
  const H = data.length * (rowH + gap) - gap + 16;
  // trapezoid widths shrink proportionally
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Patient flow funnel" className="w-full">
      {data.map((d, i) => {
        const w = W * (0.95 - i * 0.15);
        const x = (W - w) / 2;
        const y = i * (rowH + gap);
        // polygon trapezoid (slightly inset bottom)
        const inset = i < data.length - 1 ? 14 : 0;
        const bw = w - inset;
        const bx = (W - bw) / 2;
        const points = `${x},${y} ${x + w},${y} ${bx + bw},${y + rowH} ${bx},${y + rowH}`;
        const fill = ["#0F766E", "#15803D", "#2563EB", "#CA8A04", "#64748B"][i] ?? "#64748B";
        return (
          <g key={d.stage}>
            <polygon points={points} fill={fill} opacity={0.95} rx={4} />
            <text x={W / 2} y={y + rowH / 2 + 4} textAnchor="middle" fontSize={10} fontWeight={600} fill="white">
              {d.stage} · {d.count} ({d.pct}%)
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ── page ───────────────────────────────────────────────────────────────

export interface DashboardViewProps {
  isLive?: boolean;
  demoMode?: boolean;
}

export default function DashboardView({ isLive = false, demoMode = true }: DashboardViewProps) {
  const { data: health, isError } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    retry: false,
    refetchInterval: 30_000,
    staleTime: 25_000,
  });

  const now = new Date();
  const dateStr = now.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const timeStr = now.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true });

  return (
    <div className="flex flex-col gap-5 p-4 md:p-6">
      {/* Context / welcome band */}
      <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-medium text-muted-foreground">{dateStr}</p>
          <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Welcome back — real-time overview of hospital operations
            {demoMode ? " · Demo data" : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {demoMode ? (
            <Badge variant="outline" className="text-xs">
              Demo data
            </Badge>
          ) : isLive ? (
            <Badge variant="secondary" className="flex items-center gap-1.5 bg-green-600 text-white hover:bg-green-700 text-xs">
              <CheckCircle2 className="size-3" aria-hidden="true" /> Live Data
            </Badge>
          ) : null}
          <span className="text-xs text-muted-foreground">{timeStr}</span>
          {health && !isError ? (
            <Badge variant="secondary" className="flex items-center gap-1 border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-400">
              <CheckCircle2 className="size-3.5" aria-hidden="true" /> System OK
            </Badge>
          ) : isError ? (
            <Badge variant="destructive" className="flex items-center gap-1">
              <XCircle className="size-3.5" aria-hidden="true" /> API unreachable
            </Badge>
          ) : null}
        </div>
      </div>

      {/* KPI strip — 6 cards, inline SVG sparklines */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {fixtureKpis.map((kpi, idx) => {
          const icons = [Users, Stethoscope, BedDouble, Activity, FlaskConical, FileWarning];
          const Icon = icons[idx] ?? Users;
          return (
            <Card key={kpi.label} className="overflow-hidden">
              <CardHeader className="flex flex-row items-start justify-between gap-2 pb-2">
                <div className="flex items-center gap-2">
                  <span className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Icon className="size-4" aria-hidden="true" />
                  </span>
                  <CardTitle className="text-xs font-semibold leading-tight text-muted-foreground">{kpi.label}</CardTitle>
                </div>
              </CardHeader>
              <CardContent className="pt-0">
                <div className="text-2xl font-bold tracking-tight">{kpi.value}</div>
                <div className="mt-1 flex items-center gap-1.5 text-xs">
                  <span className={kpi.trend === "down" && kpi.label !== "Pending Claims" ? "text-destructive" : kpi.trend === "up" && kpi.label === "Pending Claims" ? "text-destructive" : kpi.trend === "up" ? "text-green-600" : "text-muted-foreground"}>
                    {kpi.delta}
                  </span>
                  <span className="text-muted-foreground">{kpi.deltaLabel}</span>
                </div>
                <div className="mt-3">
                  <Sparkline values={kpi.spark} color={kpi.trend === "up" ? "hsl(174 83% 30%)" : kpi.trend === "down" ? "hsl(0 84% 60%)" : "hsl(var(--muted-foreground))"} />
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Three-panel analytics row */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">Bed Occupancy</CardTitle>
              <a href="#" className="text-xs font-medium text-primary hover:underline" onClick={(e) => e.preventDefault()}>
                View ›
              </a>
            </div>
            <CardDescription>Capacity across all wards</CardDescription>
          </CardHeader>
          <CardContent>
            <DonutChart segments={fixtureBedOccupancy} label="Bed occupancy by status" centerLabel="82%" centerSub="410 / 500 beds" />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">OPD Volume Trend</CardTitle>
            <CardDescription>Last 7 days · Male / Female</CardDescription>
          </CardHeader>
          <CardContent>
            <GroupedBars data={fixtureOpdVolume} />
            <div className="mt-2 flex items-center justify-center gap-4 text-xs">
              <span className="flex items-center gap-1.5">
                <span className="inline-block size-2.5 rounded-sm" style={{ background: "hsl(174 83% 30%)" }} aria-hidden="true" /> Male
              </span>
              <span className="flex items-center gap-1.5">
                <span className="inline-block size-2.5 rounded-sm" style={{ background: "hsl(200 70% 55%)" }} aria-hidden="true" /> Female
              </span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Emergency — Acuity & Flow</CardTitle>
            <CardDescription>Triage distribution and flow</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <DonutChart segments={fixtureEmergencyAcuity} label="Emergency acuity distribution" centerLabel="87" centerSub="cases today" size={120} strokeWidth={14} />
            <div className="grid grid-cols-3 gap-2 text-center">
              {fixtureEmergencyFlow.map((f) => (
                <div key={f.label} className="rounded-lg border bg-muted/40 px-2 py-2">
                  <div className="text-lg font-bold leading-none">{f.value}</div>
                  <div className="mt-0.5 text-[11px] font-medium text-muted-foreground">{f.label}</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* OT schedule + Critical Alerts */}
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">Today&apos;s Operation Theatre Schedule</CardTitle>
              <a href="#" className="text-xs font-medium text-primary hover:underline" onClick={(e) => e.preventDefault()}>
                View All
              </a>
            </div>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="px-2 py-2 text-left font-medium">Time</th>
                  <th className="px-2 py-2 text-left font-medium">OT</th>
                  <th className="px-2 py-2 text-left font-medium">Procedure</th>
                  <th className="px-2 py-2 text-left font-medium">Patient</th>
                  <th className="px-2 py-2 text-left font-medium">Surgeon</th>
                  <th className="px-2 py-2 text-left font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {fixtureOtSchedule.map((row) => (
                  <tr key={`${row.ot}-${row.time}`} className="border-b last:border-0">
                    <td className="px-2 py-2.5">
                      <span className="inline-flex rounded-full bg-muted px-2 py-0.5 text-xs font-medium">{row.time}</span>
                    </td>
                    <td className="px-2 py-2.5 font-medium">{row.ot}</td>
                    <td className="px-2 py-2.5">{row.procedure}</td>
                    <td className="px-2 py-2.5 text-muted-foreground">{row.patient}</td>
                    <td className="px-2 py-2.5">{row.surgeon}</td>
                    <td className="px-2 py-2.5">
                      <Badge
                        variant={row.status === "Ongoing" ? "default" : row.status === "Up Next" ? "secondary" : "outline"}
                        className={
                          row.status === "Ongoing"
                            ? "bg-green-600 text-white hover:bg-green-700"
                            : row.status === "Up Next"
                              ? "bg-amber-500 text-white hover:bg-amber-600 border-transparent"
                              : ""
                        }
                      >
                        {row.status}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2 text-sm">
                <AlertTriangle className="size-4 text-destructive" aria-hidden="true" /> Critical Alerts
              </CardTitle>
              <Badge variant="destructive" className="rounded-full px-2 py-0 text-xs">
                {fixtureAlerts.length}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {fixtureAlerts.map((a) => (
              <div key={a.title} className="flex gap-3 rounded-lg border px-3 py-2.5">
                <span
                  className={
                    a.severity === "critical"
                      ? "mt-0.5 size-2 shrink-0 rounded-full bg-destructive"
                      : a.severity === "warning"
                        ? "mt-0.5 size-2 shrink-0 rounded-full bg-amber-500"
                        : "mt-0.5 size-2 shrink-0 rounded-full bg-blue-500"
                  }
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold leading-tight">{a.title}</p>
                  <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{a.detail}</p>
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">{a.time}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      {/* Lower row: Admissions/Discharges + Funnel + Department Performance */}
      <div className="grid gap-4 lg:grid-cols-12">
        <Card className="lg:col-span-6">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Clock3 className="size-4 text-muted-foreground" aria-hidden="true" /> Recent Admissions & Discharges
            </CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="px-2 py-2 text-left font-medium">Time</th>
                  <th className="px-2 py-2 text-left font-medium">UHID</th>
                  <th className="px-2 py-2 text-left font-medium">Patient</th>
                  <th className="px-2 py-2 text-left font-medium">Department</th>
                  <th className="px-2 py-2 text-left font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {fixtureAdmissions.map((r) => (
                  <tr key={r.uhid} className="border-b last:border-0">
                    <td className="px-2 py-2.5 text-xs text-muted-foreground">{r.time}</td>
                    <td className="px-2 py-2.5 font-mono text-xs">{r.uhid}</td>
                    <td className="px-2 py-2.5">
                      {r.name} <span className="text-muted-foreground">{r.ageSex}</span>
                    </td>
                    <td className="px-2 py-2.5">{r.department}</td>
                    <td className="px-2 py-2.5">
                      <Badge variant={r.status === "Admitted" ? "secondary" : "outline"} className="text-xs">
                        {r.status}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>

        <Card className="lg:col-span-3">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Patient Flow Funnel</CardTitle>
            <CardDescription>Registered → Discharged</CardDescription>
          </CardHeader>
          <CardContent>
            <FunnelChart data={fixtureFunnel} />
            <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
              {fixtureFunnel.map((s) => (
                <li key={s.stage} className="flex justify-between">
                  <span>{s.stage}</span>
                  <span className="font-medium text-foreground">
                    {s.count} · {s.pct}%
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card className="lg:col-span-3">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Department Performance</CardTitle>
            <CardDescription>OPD / IPD / occupancy</CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="px-2 py-2 text-left font-medium">Department</th>
                  <th className="px-2 py-2 text-right font-medium">OPD</th>
                  <th className="px-2 py-2 text-right font-medium">IPD</th>
                  <th className="px-2 py-2 text-left font-medium">Occupancy</th>
                </tr>
              </thead>
              <tbody>
                {fixtureDepartments.map((d) => (
                  <tr key={d.department} className="border-b last:border-0">
                    <td className="px-2 py-2.5 font-medium">{d.department}</td>
                    <td className="px-2 py-2.5 text-right tabular-nums">{d.opd}</td>
                    <td className="px-2 py-2.5 text-right tabular-nums">{d.ipd}</td>
                    <td className="px-2 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
                          <span className="block h-full rounded-full bg-primary" style={{ width: `${d.occupancy}%` }} />
                        </span>
                        <span className="text-xs tabular-nums">{d.occupancy}%</span>
                        {d.status === "High" && (
                          <Badge variant="secondary" className="bg-amber-500 text-white hover:bg-amber-600 border-transparent text-[10px] px-1.5 py-0">
                            High
                          </Badge>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
