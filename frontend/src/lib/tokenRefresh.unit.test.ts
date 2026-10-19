/**
 * tokenRefresh/apiClient — single-flight 401 recovery mechanics (UI-001).
 *
 * Pins the contract the rest of the app relies on: one shared refresh call
 * across concurrent 401s, exactly one retry per caller (no refresh loop),
 * tokens cleared when the refresh token is dead, and no refresh attempt on
 * non-401 failures.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient, ApiError } from "@/lib/apiClient";
import { useAuthStore } from "@/stores/authStore";

interface RecordedCall {
  url: string;
  authorization: string | null;
  body: string | null;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Stub global fetch and record every call's URL, auth header and body. */
function stubFetch(handler: (url: string) => Response): RecordedCall[] {
  const calls: RecordedCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const headers = new Headers(init?.headers);
      calls.push({
        url,
        authorization: headers.get("Authorization"),
        body: typeof init?.body === "string" ? init.body : null,
      });
      return handler(url);
    }),
  );
  return calls;
}

const isRefresh = (call: RecordedCall) =>
  call.url.endsWith("/auth/token/refresh/");
const isProtected = (call: RecordedCall) =>
  call.url.endsWith("/api/v1/patients/");

beforeEach(() => {
  useAuthStore.setState({
    accessToken: null,
    refreshToken: null,
    isAuthenticated: false,
  });
  sessionStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiClient 401 recovery", () => {
  it("refreshes once and retries the original request with the rotated token", async () => {
    useAuthStore.setState({
      accessToken: "access-expired",
      refreshToken: "refresh-1",
      isAuthenticated: true,
    });
    let protectedHits = 0;
    const calls = stubFetch((url) => {
      if (url.endsWith("/auth/token/refresh/")) {
        return jsonResponse(200, { access: "access-2", refresh: "refresh-2" });
      }
      protectedHits += 1;
      return protectedHits === 1
        ? jsonResponse(401, { detail: "expired" })
        : jsonResponse(200, { ok: true });
    });

    const result = await apiClient<{ ok: boolean }>("/api/v1/patients/");

    expect(result).toEqual({ ok: true });
    expect(calls.filter(isRefresh)).toHaveLength(1);
    expect(calls.find(isRefresh)?.body).toBe(
      JSON.stringify({ refresh: "refresh-1" }),
    );
    expect(calls.find(isProtected)?.authorization).toBe(
      "Bearer access-expired",
    );
    expect(calls.filter(isProtected)[1]?.authorization).toBe("Bearer access-2");
    expect(useAuthStore.getState().accessToken).toBe("access-2");
    expect(useAuthStore.getState().refreshToken).toBe("refresh-2");
  });

  it("shares one refresh between two concurrent 401s", async () => {
    useAuthStore.setState({
      accessToken: "access-expired",
      refreshToken: "refresh-1",
      isAuthenticated: true,
    });
    let protectedHits = 0;
    const calls = stubFetch((url) => {
      if (url.endsWith("/auth/token/refresh/")) {
        return jsonResponse(200, { access: "access-2" });
      }
      protectedHits += 1;
      return protectedHits <= 2
        ? jsonResponse(401, { detail: "expired" })
        : jsonResponse(200, { value: protectedHits });
    });

    const [first, second] = await Promise.all([
      apiClient<{ value: number }>("/api/v1/patients/"),
      apiClient<{ value: number }>("/api/v1/patients/"),
    ]);

    expect(first).toEqual({ value: 3 });
    expect(second).toEqual({ value: 4 });
    expect(calls.filter(isRefresh)).toHaveLength(1);
    // 2 original calls + 2 retries, all served by the one refresh above.
    expect(calls.filter(isProtected)).toHaveLength(4);
    expect(
      calls
        .filter(isProtected)
        .slice(2)
        .every((call) => call.authorization === "Bearer access-2"),
    ).toBe(true);
  });

  it("keeps the existing refresh token when the response carries no rotation", async () => {
    useAuthStore.setState({
      accessToken: "access-expired",
      refreshToken: "refresh-1",
      isAuthenticated: true,
    });
    let protectedHits = 0;
    stubFetch((url) => {
      if (url.endsWith("/auth/token/refresh/")) {
        return jsonResponse(200, { access: "access-2" });
      }
      protectedHits += 1;
      return protectedHits === 1
        ? jsonResponse(401, { detail: "expired" })
        : jsonResponse(200, { ok: true });
    });

    await expect(
      apiClient("/api/v1/patients/"),
    ).resolves.toBeDefined();
    expect(useAuthStore.getState().accessToken).toBe("access-2");
    expect(useAuthStore.getState().refreshToken).toBe("refresh-1");
  });

  it("clears the session when the refresh token is dead, and does not recurse", async () => {
    useAuthStore.setState({
      accessToken: "access-expired",
      refreshToken: "refresh-dead",
      isAuthenticated: true,
    });
    const calls = stubFetch(() => jsonResponse(401, { detail: "dead" }));

    const failure = apiClient("/api/v1/patients/");
    await expect(failure).rejects.toBeInstanceOf(ApiError);
    await expect(failure).rejects.toMatchObject({ status: 401 });

    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(useAuthStore.getState().refreshToken).toBeNull();
    expect(sessionStorage.getItem("mediflow-auth")).not.toContain(
      "refresh-dead",
    );
    // The refresh call 401s too; if it could trigger another refresh this
    // count would not settle at one.
    expect(calls.filter(isRefresh)).toHaveLength(1);
  });

  it("does not attempt a refresh on non-401 failures", async () => {
    useAuthStore.setState({
      accessToken: "access-1",
      refreshToken: "refresh-1",
      isAuthenticated: true,
    });
    const calls = stubFetch(() => jsonResponse(500, { detail: "boom" }));

    await expect(apiClient("/api/v1/patients/")).rejects.toMatchObject({
      status: 500,
    });
    expect(calls.filter(isRefresh)).toHaveLength(0);
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
  });

  it("retries at most once even when the retry still 401s", async () => {
    useAuthStore.setState({
      accessToken: "access-expired",
      refreshToken: "refresh-1",
      isAuthenticated: true,
    });
    let refreshHits = 0;
    const calls = stubFetch((url) => {
      if (url.endsWith("/auth/token/refresh/")) {
        refreshHits += 1;
        return jsonResponse(200, { access: "access-2" });
      }
      return jsonResponse(401, { detail: "still denied" });
    });

    await expect(apiClient("/api/v1/patients/")).rejects.toMatchObject({
      status: 401,
    });
    expect(calls.filter(isProtected)).toHaveLength(2);
    expect(refreshHits).toBe(1);
  });
});
