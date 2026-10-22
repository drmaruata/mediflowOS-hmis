/**
 * TokenDisplay integration tests — kiosk counter display (UI-003).
 *
 * Pins the UI_UX_design §7 "Counter token display (kiosk)" contract
 * (lines 806-830): 2 s REST polling driven by fake timers through TanStack
 * (no manual fetch-in-effect), the offline banner after two consecutive
 * failed polls with the last good token kept (§828), the behavioural
 * unmount pin (no further polls after unmount — StrictMode-safe by
 * construction), and every doc state (§823): no tokens, network error,
 * stale >6 s, unconfigured display, expired kiosk token. No login UI in any
 * state and no patient identifier ever rendered — this is a public display.
 */

import { StrictMode } from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TokenDisplay from "./TokenDisplay";
import KioskRoutes from "./__routes";
import { KIOSK_TOKEN_STORAGE_KEY } from "./kiosk.api";

const DEPARTMENT_ID = "11111111-2222-3333-4444-555555555555";
const KIOSK_TOKEN = "test-kiosk-token";
const PATIENT_ID = "99999999-8888-7777-6666-555555555555";
const QUEUE_URL = `/api/v1/tokens/queue/?department_id=${DEPARTMENT_ID}`;

const jsonResponse = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const ok = (body: unknown): Response => jsonResponse(200, body);

/** Wire-shaped token row (TokenSerializer is `fields = "__all__"`). */
const queueToken = (series: string, number: number) => ({
  id: `${series}-${number}`,
  tenant_id: "aaaaaaaa-0000-0000-0000-000000000001",
  patient_id: PATIENT_ID,
  department_id: DEPARTMENT_ID,
  series,
  number,
  priority: 0,
  status: "waiting",
  issued_at: "2026-10-21T09:00:00Z",
  called_at: null,
  done_at: null,
});

const departmentPayload = () => ({
  id: DEPARTMENT_ID,
  name: "General OPD",
});

interface RecordedCall {
  url: string;
  authorization: string | null;
}

/** Stub global fetch and record every call's URL and bearer (house pattern). */
function stubFetch(
  handler: (url: string) => Response | Promise<Response>,
): RecordedCall[] {
  const calls: RecordedCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({
        url,
        authorization: new Headers(init?.headers).get("Authorization"),
      });
      return handler(url);
    }),
  );
  return calls;
}

const stubHappyQueue = (tokens: unknown[]) =>
  stubFetch((url) =>
    url === QUEUE_URL ? ok(tokens) : ok(departmentPayload()),
  );

/** Render the screen exactly as App.tsx mounts it: the kiosk route. */
function renderKiosk(ui = <TokenDisplay />, strict = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const tree = (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/kiosk/tokens/${DEPARTMENT_ID}`]}>
        <Routes>
          <Route path="/kiosk/tokens/:displayId" element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree);
}

/**
 * Drain to a settled state. TanStack schedules observer notifications with
 * setTimeout(0), and a notification created during an advance at exactly
 * the window edge is not fired by that same advance. Three 1 ms rounds
 * cover the full cascade: round 2 fires a poll's notification, which opens
 * the department-name query, whose notification lands in round 3.
 */
const flush = async () => {
  for (let i = 0; i < 3; i += 1) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
  }
};

/** Advance fake time and flush — fires TanStack's poll and the clock tick. */
const advance = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

const queuePolls = (calls: RecordedCall[]) =>
  calls.filter((c) => c.url === QUEUE_URL).length;

beforeEach(() => {
  vi.useFakeTimers();
  window.localStorage.setItem(KIOSK_TOKEN_STORAGE_KEY, KIOSK_TOKEN);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  window.localStorage.clear();
});

describe("TokenDisplay (kiosk counter display, UI-003)", () => {
  it("renders the current and next tokens from the queue with the kiosk bearer", async () => {
    const calls = stubHappyQueue([queueToken("M", 42), queueToken("M", 43)]);

    renderKiosk();
    await flush();

    expect(screen.getByText("NOW SERVING")).toBeInTheDocument();
    expect(screen.getByText("M-042")).toBeInTheDocument();
    expect(screen.getByText("NEXT UP M-043")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "General OPD" }),
    ).toBeInTheDocument();
    expect(screen.getByText("COUNTER — General OPD")).toBeInTheDocument();
    // Public display: the patient identifier in the payload is never rendered.
    expect(document.body.textContent).not.toContain(PATIENT_ID);
    // The kiosk token authenticates the poll and is never rendered.
    expect(calls.find((c) => c.url === QUEUE_URL)?.authorization).toBe(
      `Bearer ${KIOSK_TOKEN}`,
    );
    expect(document.body.textContent).not.toContain(KIOSK_TOKEN);
  });

  it("polls every 2 s and updates the token when the queue changes", async () => {
    let queue = [queueToken("M", 42)];
    const calls = stubFetch((url) =>
      url === QUEUE_URL ? ok(queue) : ok(departmentPayload()),
    );

    renderKiosk();
    await flush();
    expect(screen.getByText("M-042")).toBeInTheDocument();
    expect(queuePolls(calls)).toBe(1);

    queue = [queueToken("M", 43)];
    await advance(2_000);
    await flush();

    expect(queuePolls(calls)).toBe(2);
    expect(screen.queryByText("M-042")).not.toBeInTheDocument();
    expect(screen.getByText("M-043")).toBeInTheDocument();
  });

  it("keeps the last good token and raises the offline banner after two failed polls", async () => {
    let failing = false;
    stubFetch((url) => {
      if (url !== QUEUE_URL) return ok(departmentPayload());
      return failing
        ? Promise.reject(new Error("network down"))
        : ok([queueToken("M", 42)]);
    });

    renderKiosk();
    await flush();
    expect(screen.getByText("M-042")).toBeInTheDocument();

    failing = true;
    await advance(2_000);
    await flush();
    // First failure: the reconnecting indicator, not yet the banner.
    expect(screen.getByText(/Reconnecting automatically/i)).toBeInTheDocument();
    expect(screen.queryByText(/Connection lost/i)).not.toBeInTheDocument();

    await advance(2_000);
    await flush();
    // Second consecutive failure: the visible offline banner, value kept (§828).
    expect(screen.getByText(/Connection lost/i)).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("M-042")).toBeInTheDocument();
  });

  it("stops polling when unmounted (StrictMode-safe interval cleanup)", async () => {
    const calls = stubHappyQueue([queueToken("M", 42)]);

    const { unmount } = renderKiosk(<TokenDisplay />, true);
    await flush();
    const before = queuePolls(calls);

    unmount();
    await advance(4_000);

    expect(queuePolls(calls)).toBe(before);
  });

  it("serves the real display on the kiosk route (replacing the R1 placeholder)", async () => {
    stubHappyQueue([queueToken("M", 42)]);

    renderKiosk(<KioskRoutes />);
    await flush();

    expect(screen.getByText("NOW SERVING")).toBeInTheDocument();
    expect(screen.queryByText(/Not available yet/i)).not.toBeInTheDocument();
  });

  it("shows the no-tokens state when the queue is empty", async () => {
    stubHappyQueue([]);

    renderKiosk();
    await flush();

    expect(screen.getByText("No tokens waiting")).toBeInTheDocument();
    expect(screen.getByText("NOW SERVING")).toBeInTheDocument();
  });

  it("shows the offline state when the network is down before any successful poll", async () => {
    stubFetch(() => Promise.reject(new Error("network down")));

    renderKiosk();
    await flush();
    expect(screen.getByText("Connecting…")).toBeInTheDocument();

    await advance(2_000);
    await flush();

    expect(screen.getByText(/Connection lost/i)).toBeInTheDocument();
    expect(screen.queryByText(/M-\d{3}/)).not.toBeInTheDocument();
  });

  it("shows the reconnecting indicator — without the banner — when the last update is stale >6 s", async () => {
    let first = true;
    stubFetch((url) => {
      if (url !== QUEUE_URL) return ok(departmentPayload());
      if (first) {
        first = false;
        return ok([queueToken("M", 42)]);
      }
      // A hung poll: neither succeeds nor fails, so only staleness degrades.
      return new Promise<Response>(() => {});
    });

    renderKiosk();
    await flush();
    expect(
      screen.queryByText(/Reconnecting automatically/i),
    ).not.toBeInTheDocument();

    await advance(8_000);

    expect(screen.getByText(/Reconnecting automatically/i)).toBeInTheDocument();
    expect(screen.queryByText(/Connection lost/i)).not.toBeInTheDocument();
    expect(screen.getByText("M-042")).toBeInTheDocument();
  });

  it("shows the safe configuration error and fetches nothing when no kiosk token is installed", async () => {
    window.localStorage.removeItem(KIOSK_TOKEN_STORAGE_KEY);
    const calls = stubFetch(() => {
      throw new Error("must not be called");
    });

    renderKiosk();
    await flush();

    expect(screen.getByText(/not configured/i)).toBeInTheDocument();
    expect(screen.getByText(/administrator/i)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
    expect(screen.queryByText(/sign in|log in/i)).not.toBeInTheDocument();
  });

  it("shows the expired-token error — never a login UI — when the API rejects the kiosk token", async () => {
    const calls = stubFetch(() =>
      jsonResponse(401, { detail: "Token is invalid or expired" }),
    );

    renderKiosk();
    await flush();

    expect(calls.some((c) => c.url === QUEUE_URL)).toBe(true);
    expect(screen.getByText(/expired/i)).toBeInTheDocument();
    expect(screen.getByText(/administrator/i)).toBeInTheDocument();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText(/sign in|log in/i)).not.toBeInTheDocument();
  });

  it("recovers without a reload once a kiosk token is installed", async () => {
    window.localStorage.removeItem(KIOSK_TOKEN_STORAGE_KEY);
    stubHappyQueue([queueToken("M", 42)]);

    renderKiosk();
    await flush();
    expect(screen.getByText(/not configured/i)).toBeInTheDocument();

    window.localStorage.setItem(KIOSK_TOKEN_STORAGE_KEY, KIOSK_TOKEN);
    await advance(1_000);
    await flush();

    expect(screen.getByText("M-042")).toBeInTheDocument();
  });

  it("recovers from two failed polls: banner and footer clear on success, last good value replaced", async () => {
    let queue = [queueToken("M", 42)];
    let failCount = 0;
    stubFetch((url) => {
      if (url !== QUEUE_URL) return ok(departmentPayload());
      if (failCount > 0) {
        failCount -= 1;
        return Promise.reject(new Error("network down"));
      }
      return ok(queue);
    });

    renderKiosk();
    await flush();
    expect(screen.getByText("M-042")).toBeInTheDocument();

    // First failure
    failCount = 1;
    await advance(2_000);
    await flush();
    expect(screen.getByText(/Reconnecting automatically/i)).toBeInTheDocument();
    expect(screen.queryByText(/Connection lost/i)).not.toBeInTheDocument();

    // Second failure — banner raised
    failCount = 1;
    await advance(2_000);
    await flush();
    expect(screen.getByText(/Connection lost/i)).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("M-042")).toBeInTheDocument(); // last good kept

    // Recovery — success clears both banner and footer, new token shown
    queue = [queueToken("M", 43)];
    failCount = 0;
    await advance(2_000);
    await flush();
    expect(screen.queryByText(/Connection lost/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText(/Reconnecting automatically/i)).not.toBeInTheDocument();
    expect(screen.getByText("M-043")).toBeInTheDocument(); // fresh value
    expect(screen.getByText(/Updated/i)).toBeInTheDocument(); // footer shows updated time without reconnecting
  });

  it("shows footer only (no banner) on a single error after recovery", async () => {
    let queue = [queueToken("M", 42)];
    let failCount = 0;
    stubFetch((url) => {
      if (url !== QUEUE_URL) return ok(departmentPayload());
      if (failCount > 0) {
        failCount -= 1;
        return Promise.reject(new Error("network down"));
      }
      return ok(queue);
    });

    renderKiosk();
    await flush();
    expect(screen.getByText("M-042")).toBeInTheDocument();

    // Two failures to raise banner
    failCount = 1;
    await advance(2_000);
    await flush();
    failCount = 1;
    await advance(2_000);
    await flush();
    expect(screen.getByText(/Connection lost/i)).toBeInTheDocument();

    // Recovery
    queue = [queueToken("M", 43)];
    failCount = 0;
    await advance(2_000);
    await flush();
    expect(screen.queryByText(/Connection lost/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Reconnecting automatically/i)).not.toBeInTheDocument();
    expect(screen.getByText("M-043")).toBeInTheDocument();

    // Single error after recovery — footer only, no banner
    failCount = 1;
    await advance(2_000);
    await flush();
    expect(screen.getByText(/Reconnecting automatically/i)).toBeInTheDocument();
    expect(screen.queryByText(/Connection lost/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText("M-043")).toBeInTheDocument(); // value unchanged
  });

  it("remount against cached query with prior errors but current success shows no banner", async () => {
    // First mount: two failures to dirty the cache
    let failCount = 0;
    stubFetch((url) => {
      if (url !== QUEUE_URL) return ok(departmentPayload());
      if (failCount > 0) {
        failCount -= 1;
        return Promise.reject(new Error("network down"));
      }
      return ok([queueToken("M", 42)]);
    });

    const { unmount } = renderKiosk();
    await flush();
    expect(screen.getByText("M-042")).toBeInTheDocument();

    failCount = 1;
    await advance(2_000);
    await flush();
    failCount = 1;
    await advance(2_000);
    await flush();
    expect(screen.getByText(/Connection lost/i)).toBeInTheDocument();

    // Unmount and remount — the cache still has errorUpdateCount >= 2
    // but the current fetch succeeds immediately
    unmount();
    failCount = 0;
    stubHappyQueue([queueToken("M", 43)]);

    renderKiosk();
    await flush();

    // No banner flash — the fresh success wins
    expect(screen.queryByText(/Connection lost/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Reconnecting automatically/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText("M-043")).toBeInTheDocument();
  });
});
