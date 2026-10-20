/**
 * End-to-end auth wiring — session, sign-out, refresh failure, MFA gate (UI-001).
 *
 * Renders the real App (module QueryClient + BrowserRouter) against a stubbed
 * fetch, so the guard/gate behaviour pinned here is the shipped one: the
 * store flip drives navigation, never window.location.
 */

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App, { queryClient } from "@/App";
import { useAuthStore } from "@/stores/authStore";

const jsonResponse = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const ok = (body: unknown): Response => jsonResponse(200, body);

const SESSION = {
  username: "clerk-a",
  tenant_id: "aaaaaaaa-0000-0000-0000-0000000000a1",
  facility_id: null,
  role: "clerk",
  permissions: ["patient_registry.view_patient"],
  allows_break_glass: false,
  requires_mfa: false,
  mfa_verified: true,
};

const PENDING_DEVICE = {
  persistent_id: "otp_totp.dev-1",
  name: "Authenticator",
  confirmed: false,
  config_url: "otpauth://totp/Mediflow:clerk-a?secret=ABC",
};

const CONFIRMED_DEVICE = {
  ...PENDING_DEVICE,
  persistent_id: "otp_totp.dev-2",
  confirmed: true,
};

interface RecordedCall {
  url: string;
  body: string | null;
}

/** Stub global fetch and record every call's URL and body. */
function stubFetch(
  handler: (url: string) => Response,
): RecordedCall[] {
  const calls: RecordedCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({
        url,
        body: typeof init?.body === "string" ? init.body : null,
      });
      return handler(url);
    }),
  );
  return calls;
}

beforeEach(() => {
  // React Router's Navigate writes window.history; a fresh BrowserRouter
  // starts wherever the previous test ended, so reset to "/" explicitly.
  window.history.replaceState(null, "", "/");
  useAuthStore.setState({
    accessToken: null,
    refreshToken: null,
    isAuthenticated: false,
  });
  sessionStorage.clear();
  queryClient.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("authentication shell", () => {
  it("sends an unauthenticated visitor to the sign-in route", async () => {
    stubFetch(() => jsonResponse(401, { detail: "anonymous" }));

    render(<App />);

    expect(await screen.findByLabelText(/email.*user id/i)).toBeInTheDocument();
  });

  it("ends the session when a refresh fails and the guard shows sign-in", async () => {
    useAuthStore.setState({
      accessToken: "access-expired",
      refreshToken: "refresh-dead",
      isAuthenticated: true,
    });
    stubFetch((url) =>
      url.endsWith("/auth/token/refresh/")
        ? jsonResponse(401, { detail: "dead" })
        : jsonResponse(401, { detail: "expired" }),
    );

    render(<App />);

    expect(await screen.findByLabelText(/email.*user id/i)).toBeInTheDocument();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(sessionStorage.getItem("mediflow-auth")).not.toContain(
      "refresh-dead",
    );
  });

  it("blacklists the refresh token before clearing the session on sign-out", async () => {
    useAuthStore.setState({
      accessToken: "access-1",
      refreshToken: "refresh-1",
      isAuthenticated: true,
    });
    const order: string[] = [];
    const calls = stubFetch((url) => {
      if (url.endsWith("/auth/token/blacklist/")) {
        order.push(
          `blacklist while authenticated=${useAuthStore.getState().isAuthenticated}`,
        );
        return ok({});
      }
      if (url.endsWith("/auth/me/")) return ok(SESSION);
      if (url.endsWith("/health/")) return ok({ status: "ok" });
      return ok({});
    });

    render(<App />);
    expect(await screen.findByText(/Welcome back/)).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "User menu" }),
    );
    expect(screen.getByText("clerk-a")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("menuitem", { name: "Sign out" }),
    );

    expect(order).toEqual(["blacklist while authenticated=true"]);
    expect(calls.find((call) => call.url.endsWith("/auth/token/blacklist/"))?.body).toBe(
      JSON.stringify({ refresh: "refresh-1" }),
    );
    expect(await screen.findByLabelText(/email.*user id/i)).toBeInTheDocument();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(sessionStorage.getItem("mediflow-auth")).not.toContain("refresh-1");
  });

  it("routes an unverified privileged user to the challenge, not the dashboard", async () => {
    useAuthStore.setState({
      accessToken: "access-1",
      refreshToken: "refresh-1",
      isAuthenticated: true,
    });
    stubFetch((url) => {
      if (url.endsWith("/auth/me/")) {
        return ok({ ...SESSION, requires_mfa: true, mfa_verified: false });
      }
      if (url.endsWith("/mfa-devices/")) return ok([PENDING_DEVICE]);
      return ok({});
    });

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: /two-factor authentication/i }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Authenticator")).toBeInTheDocument();
    expect(screen.queryByText(/Welcome back/)).not.toBeInTheDocument();
  });

  it("confirms the device, stores the minted pair and lands on the dashboard", async () => {
    useAuthStore.setState({
      accessToken: "access-1",
      refreshToken: "refresh-1",
      isAuthenticated: true,
    });
    let meCalls = 0;
    const calls = stubFetch((url) => {
      if (url.endsWith("/auth/me/")) {
        meCalls += 1;
        return ok({
          ...SESSION,
          requires_mfa: true,
          mfa_verified: meCalls > 1,
        });
      }
      if (url.endsWith("/confirm/")) {
        return ok({ status: "confirmed", access: "access-2", refresh: "refresh-2" });
      }
      if (url.endsWith("/mfa-devices/")) return ok([PENDING_DEVICE]);
      if (url.endsWith("/health/")) return ok({ status: "ok" });
      return ok({});
    });

    render(<App />);

    const code = await screen.findByLabelText(/authenticator code/i);
    await userEvent.type(code, "123456");
    await userEvent.click(
      screen.getByRole("button", { name: /verify and continue/i }),
    );

    expect(await screen.findByText(/Welcome back/)).toBeInTheDocument();
    expect(useAuthStore.getState().accessToken).toBe("access-2");
    expect(useAuthStore.getState().refreshToken).toBe("refresh-2");
    expect(calls.find((call) => call.url.endsWith("/confirm/"))?.body).toBe(
      JSON.stringify({ token: "123456" }),
    );
    // Confirm completes the session in one request: the response carries the
    // pair, so no separate rotation is made.
    expect(
      calls.find((call) => call.url.endsWith("/auth/token/refresh/")),
    ).toBeUndefined();
    expect(
      screen.queryByLabelText(/email.*user id/i),
    ).not.toBeInTheDocument();
  });

  it("verifies against a confirmed device, stores the pair and lands on the dashboard", async () => {
    useAuthStore.setState({
      accessToken: "access-1",
      refreshToken: "refresh-1",
      isAuthenticated: true,
    });
    let meCalls = 0;
    const calls = stubFetch((url) => {
      if (url.endsWith("/auth/me/")) {
        meCalls += 1;
        return ok({
          ...SESSION,
          requires_mfa: true,
          mfa_verified: meCalls > 1,
        });
      }
      if (url.endsWith("/auth/mfa/verify/")) {
        return ok({ access: "access-2", refresh: "refresh-2" });
      }
      if (url.endsWith("/mfa-devices/")) return ok([CONFIRMED_DEVICE]);
      if (url.endsWith("/health/")) return ok({ status: "ok" });
      return ok({});
    });

    render(<App />);

    const code = await screen.findByLabelText(/authenticator code/i);
    await userEvent.type(code, "654321");
    await userEvent.click(
      screen.getByRole("button", { name: /verify and continue/i }),
    );

    expect(await screen.findByText(/Welcome back/)).toBeInTheDocument();
    expect(useAuthStore.getState().accessToken).toBe("access-2");
    expect(useAuthStore.getState().refreshToken).toBe("refresh-2");
    expect(
      calls.find((call) => call.url.endsWith("/auth/mfa/verify/"))?.body,
    ).toBe(JSON.stringify({ token: "654321" }));
  });

  it("keeps the user on the challenge when the code is wrong", async () => {
    useAuthStore.setState({
      accessToken: "access-1",
      refreshToken: "refresh-1",
      isAuthenticated: true,
    });
    stubFetch((url) => {
      if (url.endsWith("/auth/me/")) {
        return ok({ ...SESSION, requires_mfa: true, mfa_verified: false });
      }
      if (url.endsWith("/auth/mfa/verify/")) {
        return jsonResponse(400, { token: "Invalid token." });
      }
      if (url.endsWith("/mfa-devices/")) return ok([CONFIRMED_DEVICE]);
      return ok({});
    });

    render(<App />);

    const code = await screen.findByLabelText(/authenticator code/i);
    await userEvent.type(code, "000000");
    await userEvent.click(
      screen.getByRole("button", { name: /verify and continue/i }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /didn't match/i,
    );
    expect(window.location.pathname).toBe("/mfa");
  });

  it("keeps the user on the challenge with an honest notice when the session still cannot be verified", async () => {
    useAuthStore.setState({
      accessToken: "access-1",
      refreshToken: "refresh-1",
      isAuthenticated: true,
    });
    let confirmed = false;
    stubFetch((url) => {
      if (url.endsWith("/auth/me/")) {
        return ok({ ...SESSION, requires_mfa: true, mfa_verified: false });
      }
      if (url.endsWith("/confirm/")) {
        confirmed = true;
        return ok({ status: "confirmed" });
      }
      if (url.endsWith("/auth/token/refresh/")) {
        return ok({ access: "access-2", refresh: "refresh-2" });
      }
      if (url.endsWith("/mfa-devices/")) {
        // TOTPEnrolViewSet.confirm flips device.confirmed, so the
        // post-confirm list holds nothing pending — the honest panel must
        // win over the "No pending authenticator" dead end.
        return ok([{ ...PENDING_DEVICE, confirmed }]);
      }
      return ok({});
    });

    render(<App />);

    const code = await screen.findByLabelText(/authenticator code/i);
    await userEvent.type(code, "123456");
    await userEvent.click(
      screen.getByRole("button", { name: /verify and continue/i }),
    );

    const panel = await screen.findByRole("status");
    expect(panel).toHaveTextContent(
      "Authenticator confirmed. This deployment cannot yet issue a verified session — sign out and try again later, or contact your administrator.",
    );
    expect(window.location.pathname).toBe("/mfa");
    expect(
      screen.queryByText(/No pending authenticator/i),
    ).not.toBeInTheDocument();
  });
});
