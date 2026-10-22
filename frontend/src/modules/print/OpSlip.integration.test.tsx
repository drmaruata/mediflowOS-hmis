/**
 * OpSlip print integration tests (UI-006, HW-001).
 *
 * Pins the print view contract: the page fetches the OP slip payload from
 * GET /api/v1/visits/{visitId}/op-slip/ (OpSlipView), renders UHID, token,
 * department, facility, dates, and a QR code of the UHID using the existing
 * QRCodeViewSet._encode_data format (HIP[-counter][-department_id]). The
 * print button calls window.print(). Print CSS applies @media print rules
 * for 80mm thermal and A4. Error states (404/401/500) show user-visible
 * messages, not a blank page.
 */

import { StrictMode } from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import OpSlip from "./OpSlip";

const VISIT_ID = "11111111-1111-4111-8111-111111111111";
const TENANT_ID = "aaaaaaaa-0000-0000-0000-0000000000a1";

const SLIP_PAYLOAD = {
  uhid: "UHID-202610-000042",
  patient_name: "Asha Lakshmi",
  token: { series: "A", number: 14 },
  department: "General Medicine",
  facility: "City Hospital",
  issued_at: "2026-10-21T09:30:00Z",
  visit_date: "2026-10-21",
};

const SESSION = {
  username: "clerk-a",
  tenant_id: TENANT_ID,
  facility_id: null,
  role: "clerk",
  permissions: [],
  allows_break_glass: false,
  requires_mfa: false,
  mfa_verified: true,
};

const jsonResponse = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const ok = (body: unknown): Response => jsonResponse(200, body);

interface RecordedCall {
  url: string;
  method: string;
  body: string | null;
}

function stubFetch(
  handler: (url: string, method: string, body: Record<string, unknown> | null) => Response,
): RecordedCall[] {
  const calls: RecordedCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const rawBody = typeof init?.body === "string" ? init.body : null;
      calls.push({ url, method, body: rawBody });
      let body: Record<string, unknown> | null = null;
      if (rawBody !== null) {
        try {
          body = JSON.parse(rawBody) as Record<string, unknown>;
        } catch {
          body = null;
        }
      }
      return handler(url, method, body);
    }),
  );
  return calls;
}

function renderOpSlip(ui = <OpSlip />, strict = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/print/op-slip/${VISIT_ID}`]}>
        <Routes>
          <Route path="/print/op-slip/:visitId" element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree);
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("OpSlip print view (UI-006, HW-001)", () => {
  it("renders the slip with UHID, token, department, facility, dates, and QR code", async () => {
    stubFetch((url, _method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.endsWith(`/api/v1/visits/${VISIT_ID}/op-slip/`)) return ok(SLIP_PAYLOAD);
      return ok([]);
    });

    renderOpSlip();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    // Print CSS root class
    expect(document.documentElement).toHaveAttribute("data-print");

    // Slip content
    expect(screen.getByText("UHID-202610-000042")).toBeInTheDocument();
    expect(screen.getByText("Asha Lakshmi")).toBeInTheDocument();
    expect(screen.getByText("General Medicine")).toBeInTheDocument();
    expect(screen.getByText("City Hospital")).toBeInTheDocument();
    expect(screen.getByText("A-014")).toBeInTheDocument(); // token formatted as series-number
    expect(screen.getByText("2026-10-21")).toBeInTheDocument(); // visit_date

    // Print button exists and is wired
    const printButton = screen.getByRole("button", { name: /print/i });
    expect(printButton).toBeInTheDocument();

    // QR code element exists (SVG or canvas)
    const qrElement = document.querySelector('[data-testid="op-slip-qr"]') ?? document.querySelector("svg") ?? document.querySelector("canvas");
    expect(qrElement).toBeInTheDocument();
  });

  it("print button calls window.print", async () => {
    stubFetch((url, _method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.endsWith(`/api/v1/visits/${VISIT_ID}/op-slip/`)) return ok(SLIP_PAYLOAD);
      return ok([]);
    });

    const printSpy = vi.spyOn(window, "print").mockImplementation(() => {});

    renderOpSlip();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    const printButton = screen.getByRole("button", { name: /print/i });
    await act(async () => {
      printButton.click();
    });

    expect(printSpy).toHaveBeenCalledTimes(1);
    printSpy.mockRestore();
  });

  it("applies print CSS (data-print class on root)", async () => {
    stubFetch((url, _method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.endsWith(`/api/v1/visits/${VISIT_ID}/op-slip/`)) return ok(SLIP_PAYLOAD);
      return ok([]);
    });

    renderOpSlip();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    // The print CSS sets data-print on the root element
    expect(document.documentElement).toHaveAttribute("data-print");
  });

  it("shows user-visible error for 404 (visit not found)", async () => {
    stubFetch((url, _method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.endsWith(`/api/v1/visits/${VISIT_ID}/op-slip/`)) return jsonResponse(404, { detail: "Not found." });
      return ok([]);
    });

    renderOpSlip();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    expect(screen.getByText(/visit not found/i)).toBeInTheDocument();
    expect(screen.queryByText("UHID-202610-000042")).not.toBeInTheDocument();
  });

  it("shows user-visible error for 401 (unauthenticated)", async () => {
    stubFetch((url, _method) => {
      if (url.endsWith("/api/v1/auth/me/")) return jsonResponse(401, { detail: "Authentication credentials were not provided." });
      if (url.endsWith(`/api/v1/visits/${VISIT_ID}/op-slip/`)) return jsonResponse(401, { detail: "Authentication credentials were not provided." });
      return ok([]);
    });

    renderOpSlip();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    expect(screen.getByText(/please sign in to print/i)).toBeInTheDocument();
  });

  it("shows user-visible error for 500 (server error)", async () => {
    stubFetch((url, _method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.endsWith(`/api/v1/visits/${VISIT_ID}/op-slip/`)) return jsonResponse(500, { detail: "Internal server error." });
      return ok([]);
    });

    renderOpSlip();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    expect(screen.getByText(/internal server error/i)).toBeInTheDocument();
  });

  it("handles null token (visit without issued token)", async () => {
    const slipWithoutToken = { ...SLIP_PAYLOAD, token: null, issued_at: null };
    stubFetch((url, _method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.endsWith(`/api/v1/visits/${VISIT_ID}/op-slip/`)) return ok(slipWithoutToken);
      return ok([]);
    });

    renderOpSlip();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    expect(screen.getByText("UHID-202610-000042")).toBeInTheDocument();
    expect(screen.getByText("Asha Lakshmi")).toBeInTheDocument();
    // Token should show "Not issued" or similar
    expect(screen.getByText(/not issued/i)).toBeInTheDocument();
  });

  it("QR code uses the UHID as payload", async () => {
    stubFetch((url, _method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.endsWith(`/api/v1/visits/${VISIT_ID}/op-slip/`)) return ok(SLIP_PAYLOAD);
      return ok([]);
    });

    renderOpSlip();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    // The QR code should encode the UHID
    const qrElement = document.querySelector('[data-testid="op-slip-qr"]');
    expect(qrElement).toBeInTheDocument();
    // QR code payload should be the UHID (or HIP format, but we use UHID for patient-facing slip)
    expect(qrElement).toHaveAttribute("data-qr-payload", "UHID-202610-000042");
  });
});