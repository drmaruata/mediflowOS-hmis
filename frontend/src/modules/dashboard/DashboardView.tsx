/**
 * Dashboard summary stats and system-health indicator.
 *
 * Polls the liveness probe every 30 s (architecture doc §5); all other data
 * fetching uses REST polling — not Channels (§8.4 "Counter display screens
 * use REST polling/refetching").
 *
 * Charts are hand-rolled inline SVG — no @ant-design/charts or recharts
 * dependency to avoid a full doc-sync checklist.
 */

import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Users,
  BedDouble,
  FlaskConical,
  CheckCircle2,
  XCircle,
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

interface StatCardProps {
  title: string;
  value: string | number;
  description: string;
  icon: React.ReactNode;
}

function StatCard({ title, value, description, icon }: StatCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <span className="text-muted-foreground" aria-hidden="true">
          {icon}
        </span>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        <p className="mt-1 text-xs text-muted-foreground">{description}</p>
      </CardContent>
    </Card>
  );
}

/** Minimal donut chart rendered with inline SVG — no external chart library. */
function DonutChart({
  segments,
  label,
}: {
  segments: Array<{ value: number; color: string; name: string }>;
  label: string;
}) {
  const total = segments.reduce((s, seg) => s + seg.value, 0);
  const radius = 40;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  return (
    <div className="flex items-center gap-6">
      <svg
        width={100}
        height={100}
        viewBox="0 0 100 100"
        role="img"
        aria-label={label}
      >
        <circle cx={50} cy={50} r={radius} fill="none" strokeWidth={16} stroke="hsl(var(--muted))" />
        {segments.map((seg) => {
          const dash = (seg.value / total) * circumference;
          const el = (
            <circle
              key={seg.name}
              cx={50}
              cy={50}
              r={radius}
              fill="none"
              strokeWidth={16}
              stroke={seg.color}
              strokeDasharray={`${dash} ${circumference - dash}`}
              strokeDashoffset={-(offset / total) * circumference + circumference * 0.25}
              strokeLinecap="butt"
            />
          );
          offset += seg.value;
          return el;
        })}
        <text
          x={50}
          y={54}
          textAnchor="middle"
          className="text-xs fill-foreground font-semibold"
          fontSize={14}
        >
          {total}
        </text>
      </svg>

      <ul className="flex flex-col gap-1.5">
        {segments.map((seg) => (
          <li key={seg.name} className="flex items-center gap-2 text-sm">
            <span
              className="inline-block size-2.5 rounded-sm"
              style={{ backgroundColor: seg.color }}
              aria-hidden="true"
            />
            <span className="text-muted-foreground">{seg.name}</span>
            <span className="ml-auto font-medium">{seg.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

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

  return (
    <main className="flex flex-col gap-6 p-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Today's operational summary{demoMode ? " · Demo data" : ""}
          </p>
        </div>

        {demoMode ? (
          <Badge variant="outline" className="text-xs">Demo</Badge>
        ) : isLive ? (
          <Badge variant="secondary" className="flex items-center gap-1.5 text-xs">
            <CheckCircle2 className="size-3" aria-hidden="true" />
            Live Data
          </Badge>
        ) : null}

        {/* System health pill */}
        {health && !isError ? (
          <Badge
            variant="secondary"
            className="flex items-center gap-1.5 border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-400"
          >
            <CheckCircle2 className="size-3.5" aria-hidden="true" />
            System OK
          </Badge>
        ) : isError ? (
          <Badge
            variant="destructive"
            className="flex items-center gap-1.5"
          >
            <XCircle className="size-3.5" aria-hidden="true" />
            API unreachable
          </Badge>
        ) : null}
      </div>

      {/* KPI stat cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="OPD Registrations"
          value={124}
          description="Today across all counters"
          icon={<Users className="size-4" />}
        />
        <StatCard
          title="IPD Occupancy"
          value="78%"
          description="68 / 87 beds occupied"
          icon={<BedDouble className="size-4" />}
        />
        <StatCard
          title="Lab Orders"
          value={203}
          description="Pending: 14 · Completed: 189"
          icon={<FlaskConical className="size-4" />}
        />
        <StatCard
          title="Active Patients"
          value={91}
          description="Currently admitted"
          icon={<Activity className="size-4" />}
        />
      </div>

      {/* Charts row */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Bed Status</CardTitle>
            <CardDescription>Current occupancy by ward type</CardDescription>
          </CardHeader>
          <CardContent>
            <DonutChart
              label="Bed occupancy by ward type"
              segments={[
                { name: "General", value: 42, color: "hsl(174 83% 30%)" },
                { name: "ICU", value: 10, color: "hsl(174 60% 50%)" },
                { name: "Maternity", value: 8, color: "hsl(200 70% 55%)" },
                { name: "Paediatric", value: 8, color: "hsl(40 90% 55%)" },
                { name: "Available", value: 19, color: "hsl(var(--muted-foreground))" },
              ]}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">OPD Queue</CardTitle>
            <CardDescription>Tokens issued vs completed today</CardDescription>
          </CardHeader>
          <CardContent>
            <DonutChart
              label="OPD token status"
              segments={[
                { name: "Completed", value: 97, color: "hsl(174 83% 30%)" },
                { name: "Waiting", value: 18, color: "hsl(40 90% 55%)" },
                { name: "Called", value: 9, color: "hsl(200 70% 55%)" },
              ]}
            />
          </CardContent>
        </Card>
      </div>

      {/* Placeholder notice for unimplemented modules */}
      <Card className="border-dashed">
        <CardContent className="flex items-center gap-3 py-4 text-sm text-muted-foreground">
          <Activity className="size-4 shrink-0" aria-hidden="true" />
          <span>
            Module-level views (OPD, IPD, Pharmacy, LIS, Quality OS…) will appear here
            as each module is implemented. Navigation entries are disabled until their
            route exists.
          </span>
        </CardContent>
      </Card>
    </main>
  );
}
