/**
 * TokenDisplay — public counter token display (UI-003, UI_UX_design §7
 * "Counter token display (kiosk)", lines 806-830).
 *
 * A full-screen wall display outside the interactive-auth shell: no login
 * prompt in any state (§824) and no patient names — the queue response's
 * patient_id is neither typed nor rendered (§825). Data is REST polling
 * only (§14: polling, not Channels): TanStack owns the 2 s interval and
 * keeps the last good value across failures; the wall clock is the one
 * local timer and renders nothing from the server.
 *
 * States (§823): initial → "Connecting…"; success → the display; empty
 * queue → "No tokens waiting". Degradation is one status surface at two
 * severities: the footer appends "Reconnecting automatically" from the
 * first failed poll or >6 s staleness, and two consecutive failures raise
 * the offline banner while the last good value stays (§828). The queue
 * endpoint returns only status="waiting" rows ordered by number, so the
 * head of the queue is the now-serving token and queue turnover is what
 * updates the display (§827). A missing kiosk token renders the safe
 * configuration error and a rejected (401) one the expired-token error —
 * both administrator instructions, never a login form (§829).
 */

import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from "@/components/ui/card";
import { KioskApiError, fetchDepartment, fetchTokenQueue, getKioskToken } from "./kiosk.api";

const POLL_INTERVAL_MS = 2_000;
const STALE_AFTER_MS = 6_000;

function formatToken(token: { series: string; number: number }): string {
  return `${token.series}-${String(token.number).padStart(3, "0")}`;
}

function formatClock(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour12: false });
}

/** Wall clock — the only local timer; StrictMode-safe by symmetric cleanup. */
function useClock(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(id);
  }, []);
  return now;
}

function OfflineBanner({ hasLastUpdate }: { hasLastUpdate: boolean }) {
  return (
    <div
      role="status"
      className="w-full bg-destructive px-8 py-4 text-2xl font-semibold text-destructive-foreground"
    >
      {hasLastUpdate
        ? "Connection lost — displaying the last update. Reconnecting automatically."
        : "Connection lost — reconnecting automatically. Waiting for the network."}
    </div>
  );
}

function ConfigurationScreen({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-svh items-center justify-center bg-card p-4">
      <Card className="w-full max-w-xl">
        <CardHeader>
          <h1 className="text-xl font-bold tracking-tight text-card-foreground">
            Token display unavailable
          </h1>
          <CardDescription>This kiosk cannot show tokens right now.</CardDescription>
        </CardHeader>
        <CardContent>
          <p role="status" className="text-sm text-muted-foreground">
            {children}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

export default function TokenDisplay() {
  const displayId = useParams<{ displayId: string }>().displayId ?? "";
  const kioskToken = getKioskToken();
  const now = useClock();
  const configured = kioskToken !== null && displayId !== "";

  const queueQuery = useQuery({
    queryKey: ["kiosk", "token-queue", displayId],
    queryFn: () => fetchTokenQueue(displayId),
    enabled: configured,
    // retry: false so a failed poll counts immediately — the two-failure
    // banner (§828) must not wait out TanStack's default retry ladder.
    retry: false,
    refetchInterval: POLL_INTERVAL_MS,
  });

  const departmentQuery = useQuery({
    // The department name is decoration: it only starts once the queue has
    // succeeded, so it can never 401-crash the display on its own and never
    // adds a second polling loop.
    queryKey: ["kiosk", "department", displayId],
    queryFn: () => fetchDepartment(displayId),
    enabled: configured && queueQuery.dataUpdatedAt > 0,
    retry: false,
    staleTime: Infinity,
  });

  const tokens = queueQuery.data;
  const current = tokens !== undefined && tokens.length > 0 ? tokens[0] : undefined;
  const next = tokens !== undefined && tokens.length > 1 ? tokens[1] : undefined;

  // TanStack 5.104 resets failureCount at each fetch start (it stays 1 with
  // retry: false), so the doc's "two consecutive failed polls" (§828) is
  // counted from errorUpdateCount — monotone per error event — with any
  // success clearing the tally. Guards make the double StrictMode effect
  // run a no-op, so the count cannot inflate.
  // seenErrorsRef is seeded on first observation so a remount against a
  // cached query with errorUpdateCount >= 2 but current success computes
  // delta 0 and does not flash the offline banner.
  const [failedPolls, setFailedPolls] = useState(0);
  const seenErrorsRef = useRef<number | null>(null);
  useEffect(() => {
    if (seenErrorsRef.current === null) {
      seenErrorsRef.current = queueQuery.errorUpdateCount;
      return;
    }
    const newErrors = queueQuery.errorUpdateCount - seenErrorsRef.current;
    seenErrorsRef.current = queueQuery.errorUpdateCount;
    if (newErrors > 0) {
      setFailedPolls((count) => count + newErrors);
    } else if (newErrors < 0 || queueQuery.isSuccess) {
      // Re-baseline when the query key changes; any success clears it.
      setFailedPolls(0);
    }
  }, [queueQuery.errorUpdateCount, queueQuery.isSuccess]);

  const offline = failedPolls >= 2;
  const reconnecting =
    queueQuery.isError ||
    (tokens !== undefined && now - queueQuery.dataUpdatedAt > STALE_AFTER_MS);
  const expired =
    queueQuery.error instanceof KioskApiError && queueQuery.error.status === 401;
  const departmentName = departmentQuery.data?.name;

  if (!configured) {
    return (
      <ConfigurationScreen>
        This display is not configured. Ask an administrator to install its
        kiosk access token.
      </ConfigurationScreen>
    );
  }

  if (expired) {
    return (
      <ConfigurationScreen>
        The kiosk access token for this display has expired. Ask an
        administrator to renew it.
      </ConfigurationScreen>
    );
  }

  if (tokens === undefined) {
    if (offline) {
      return (
        <div className="flex min-h-svh flex-col bg-card text-card-foreground">
          <OfflineBanner hasLastUpdate={false} />
          <p className="flex flex-1 items-center justify-center text-3xl text-muted-foreground">
            Waiting for the network…
          </p>
        </div>
      );
    }
    return (
      <div className="flex min-h-svh items-center justify-center bg-card p-4">
        <p role="status" className="text-3xl text-muted-foreground">
          Connecting…
        </p>
      </div>
    );
  }

  return (
    <div className="flex min-h-svh flex-col bg-card text-card-foreground">
      {offline && <OfflineBanner hasLastUpdate={tokens.length > 0} />}
      <header className="flex items-start justify-between p-8">
        <h1 className="text-4xl font-bold">{departmentName ?? "Token display"}</h1>
        <time className="text-4xl tabular-nums text-muted-foreground">
          {formatClock(now)}
        </time>
      </header>
      <main className="flex flex-1 flex-col items-center justify-center gap-8 pb-16 text-center">
        <p className="text-4xl font-semibold tracking-widest text-muted-foreground">
          NOW SERVING
        </p>
        {/* aria-live="polite": screen readers hear the token update without
            the display stealing focus. */}
        <p
          aria-live="polite"
          className="text-9xl font-bold tabular-nums"
        >
          {current ? formatToken(current) : "No tokens waiting"}
        </p>
        {next !== undefined && (
          <p className="text-4xl text-muted-foreground">
            NEXT UP {formatToken(next)}
          </p>
        )}
        <p className="text-3xl text-muted-foreground">
          {["COUNTER", departmentName].filter(Boolean).join(" — ")}
        </p>
      </main>
      <footer className="p-8">
        <p className="text-2xl text-muted-foreground">
          Updated {formatClock(queueQuery.dataUpdatedAt)}
          {reconnecting && " • Reconnecting automatically"}
        </p>
      </footer>
    </div>
  );
}
