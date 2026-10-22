/**
 * Admin screens integration tests (TEN-004, TEN-007, TEN-008, AUD-003).
 *
 * Pins the contract the backend already enforces rather than any client-side
 * re-implementation of it: the users list is the tenant-scoped GET /users/
 * surface with deactivation as the only offboarding path (TEN-008 — no DELETE
 * verb routes, so the UI must not offer one), the roles matrix writes the
 * exact `permissions` bundle the token claim will carry and its save
 * invalidates the roles list (TEN-004), the configuration edit surface
 * PATCHes rows the backend effective-dates and audits with no permission
 * claim of its own (SET-010/012 — nothing beyond authentication gates these
 * viewsets, and the UI mirrors that honestly instead of inventing a gate),
 * the audit drill-down issues ?entity_type=&entity_id= filtered requests
 * from shareable URLs (AUD-003), and break-glass sends the reason in the
 * X-Break-Glass-Reason header with submit blocked until the reason is
 * non-empty (TEN-007).
 *
 * UI-side claim gating is cosmetic and these tests treat it as such: a
 * missing claim hides the write affordances, it never replaces the server's
 * refusal as the thing that stops a write.
 */

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AuditLog from "./AuditLog";
import BreakGlassDialog from "./BreakGlassDialog";
import DepartmentsWardsBeds from "./DepartmentsWardsBeds";
import Roles from "./Roles";
import Users from "./Users";
import PatientDetail from "@/modules/patient_registry/PatientDetail";
import { useAuthStore } from "@/stores/authStore";
import type { Patient } from "@/modules/patient_registry/patient.api";

const jsonResponse = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const ok = (body: unknown): Response => jsonResponse(200, body);
const created = (body: unknown): Response => jsonResponse(201, body);

const TENANT = "aaaaaaaa-0000-0000-0000-0000000000a1";
const PATIENT_ID = "11111111-1111-4111-8111-111111111111";
const DEPARTMENT_ID = "22222222-2222-4222-8222-222222222222";
const WARD_ID = "33333333-3333-4333-8333-333333333333";
const BED_ID = "44444444-4444-4444-8444-444444444444";
const ROLE_ID = "77777777-7777-4777-8777-777777777777";
const USER_ID = "88888888-8888-4888-8888-888888888888";
const SECOND_USER_ID = "99999999-9999-4999-8999-999999999999";
const FACILITY_ID = "66666666-6666-4666-8666-666666666666";

const session = (overrides: Record<string, unknown> = {}) => ({
  username: "admin-a",
  tenant_id: TENANT,
  facility_id: null,
  role: "Tenant admin",
  permissions: ["identity.users.manage", "identity.roles.write"],
  allows_break_glass: true,
  requires_mfa: false,
  mfa_verified: true,
  ...overrides,
});

const role = (overrides: Record<string, unknown> = {}) => ({
  id: ROLE_ID,
  name: "Tenant admin",
  permissions: ["identity.users.manage"],
  require_mfa: true,
  allows_break_glass: true,
  created_at: "2026-10-01T00:00:00Z",
  ...overrides,
});

const ROLE_PAGE = { count: 1, next: null, previous: null, results: [role()] };

const USERS_PAGE = {
  count: 2,
  next: null,
  previous: null,
  results: [
    {
      id: USER_ID,
      username: "ward-nurse",
      email: "nurse@hospital.in",
      date_joined: "2026-10-01T00:00:00Z",
      role_id: ROLE_ID,
      facility_id: null,
      active: true,
    },
    {
      id: SECOND_USER_ID,
      username: "offboarded-clerk",
      email: "",
      date_joined: "2026-10-02T00:00:00Z",
      role_id: null,
      facility_id: null,
      active: false,
    },
  ],
};

const DEPARTMENT = {
  id: DEPARTMENT_ID,
  facility: FACILITY_ID,
  name: "General Medicine",
  opd_enabled: true,
  ipd_enabled: false,
  active: true,
  effective_from: "2026-10-01",
  effective_to: null,
};

const WARD = {
  id: WARD_ID,
  department: DEPARTMENT_ID,
  name: "Female ward",
  type_tag: "Medical",
  active: true,
};

const BED = {
  id: BED_ID,
  ward: WARD_ID,
  bed_number: "B-01",
  functional: true,
  occupied: false,
  active: true,
};

const EMPTY_PAGE = { count: 0, next: null, previous: null, results: [] };

const auditEvent = (overrides: Record<string, unknown> = {}) => ({
  id: "c0c0c0c0-0000-4000-8000-00000000c0c1",
  tenant_id: TENANT,
  user_id: USER_ID,
  action: "read",
  entity_type: "registry.patient",
  entity_id: PATIENT_ID,
  reason: null,
  source: null,
  source_ip: "127.0.0.1",
  occurred_at: "2026-10-21T05:00:00Z",
  hash_chain: "",
  ...overrides,
});

const patient = (overrides: Partial<Patient> = {}): Patient => ({
  id: PATIENT_ID,
  tenant_id: TENANT,
  uhid: "UHID-202610-000001",
  abha_number: null,
  abha_address: null,
  verification_status: "pending",
  verified_at: null,
  demographics: { name: "Asha Lakshmi", gender: "female", dob: "1984-03-12" },
  contact: { mobile: "9876543210" },
  address: null,
  scheme_category: null,
  consent_flags: {},
  intake_channel: "counter",
  created_at: "2026-10-21T04:31:00Z",
  ...overrides,
});

interface RecordedCall {
  url: string;
  method: string;
  body: string | null;
  headers: Record<string, string>;
}

type FetchHandler = (
  url: string,
  method: string,
  body: Record<string, unknown> | null,
) => Response;

/** Stub global fetch, record every call (headers included), route by URL + method. */
function stubFetch(handler: FetchHandler): RecordedCall[] {
  const calls: RecordedCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const rawBody = typeof init?.body === "string" ? init.body : null;
      const headers = init?.headers
        ? Object.fromEntries(new Headers(init.headers).entries())
        : {};
      calls.push({ url, method, body: rawBody, headers });
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

const findCalls = (calls: RecordedCall[], url: string, method: string) =>
  calls.filter(
    (c) => c.url.split("?")[0].endsWith(url) && c.method === method,
  );

/**
 * vi.waitUntil (not vi.waitFor): a call record only exists once the request
 * was actually issued, so the assertion must not run against a missing call.
 */
const awaitCall = async (
  calls: RecordedCall[],
  url: string,
  method: string,
): Promise<RecordedCall> => {
  const call = await vi.waitUntil(() =>
    findCalls(calls, url, method).length > 0
      ? findCalls(calls, url, method)[0]
      : undefined,
  );
  if (call === undefined) throw new Error(`expected a ${method} ${url} call`);
  return call;
};

const parsedBody = (call: RecordedCall): Record<string, unknown> =>
  JSON.parse(call.body ?? "{}") as Record<string, unknown>;

/** Mount the admin screens under their real route paths. */
function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/admin/users" element={<Users />} />
          <Route path="/admin/roles" element={<Roles />} />
          <Route
            path="/admin/departments"
            element={<DepartmentsWardsBeds section="departments" />}
          />
          <Route
            path="/admin/wards-beds"
            element={<DepartmentsWardsBeds section="wards-beds" />}
          />
          <Route path="/admin/audit" element={<AuditLog />} />
          <Route path="/patients/:id" element={<PatientDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BreakGlassDialog
        open
        onOpenChange={() => {}}
        resourceType="registry.patient"
        resourceId={PATIENT_ID}
        resourceLabel="UHID-202610-000001"
      />
    </QueryClientProvider>,
  );
}

const rowOf = (cellText: string | RegExp) => {
  const row = screen.getByRole("cell", { name: cellText }).closest("tr");
  if (row === null) throw new Error(`no table row for ${String(cellText)}`);
  return row;
};

beforeEach(() => {
  useAuthStore.setState({
    accessToken: "test-access",
    refreshToken: "test-refresh",
    isAuthenticated: true,
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Users", () => {
  it("renders the user list from the API with role names and status text", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(session());
      if (url.split("?")[0].endsWith("/api/v1/users/")) return ok(USERS_PAGE);
      if (url.split("?")[0].endsWith("/api/v1/roles/")) return ok(ROLE_PAGE);
      return ok(EMPTY_PAGE);
    });

    renderAt("/admin/users");
    const list = await screen.findByRole("region", { name: "Users" });
    expect(
      await within(list).findByRole("cell", { name: "ward-nurse" }),
    ).toBeInTheDocument();
    expect(within(list).getByRole("cell", { name: "Tenant admin" })).toBeInTheDocument();
    // Status is explicit text, never colour alone (design.md §23).
    expect(within(list).getByText("Active")).toBeInTheDocument();
    expect(within(list).getByText("Deactivated")).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Invite user" }),
    ).toBeInTheDocument();
  });

  it("hides the invite form and the deactivate action when the session lacks identity.users.manage", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/"))
        return ok(session({ permissions: [] }));
      if (url.split("?")[0].endsWith("/api/v1/users/")) return ok(USERS_PAGE);
      if (url.split("?")[0].endsWith("/api/v1/roles/")) return ok(ROLE_PAGE);
      return ok(EMPTY_PAGE);
    });

    renderAt("/admin/users");
    // Reads stay available: the backend gates writes only (WritePermissionMixin).
    expect(
      await screen.findByRole("cell", { name: "ward-nurse" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Invite user" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Deactivate" }),
    ).not.toBeInTheDocument();
  });

  it("creates a user through the invite form and refetches the list", async () => {
    const calls = stubFetch((url, method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(session());
      if (url.split("?")[0].endsWith("/api/v1/users/") && method === "POST") {
        return created(USERS_PAGE.results[0]);
      }
      if (url.split("?")[0].endsWith("/api/v1/users/")) return ok(USERS_PAGE);
      if (url.split("?")[0].endsWith("/api/v1/roles/")) return ok(ROLE_PAGE);
      return ok(EMPTY_PAGE);
    });

    renderAt("/admin/users");
    const invite = await screen.findByRole("region", { name: "Invite user" });
    await userEvent.type(within(invite).getByLabelText(/username/i), "audit-clerk");
    await userEvent.type(within(invite).getByLabelText(/^email/i), "audit@hospital.in");
    await userEvent.type(within(invite).getByLabelText(/password/i), "a-long-password-12");
    await userEvent.selectOptions(within(invite).getByLabelText(/^role/i), ROLE_ID);
    await userEvent.click(within(invite).getByRole("button", { name: "Add user" }));

    const createCall = await awaitCall(calls, "/api/v1/users/", "POST");
    expect(parsedBody(createCall)).toMatchObject({
      username: "audit-clerk",
      email: "audit@hospital.in",
      password: "a-long-password-12",
      role_id: ROLE_ID,
    });
    // The save invalidates the users list — the refetch is the proof.
    await waitFor(() =>
      expect(findCalls(calls, "/api/v1/users/", "GET").length).toBeGreaterThanOrEqual(2),
    );
  });

  it("deactivates a user only after an explicit confirmation", async () => {
    const calls = stubFetch((url, method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(session());
      if (
        url.split("?")[0].endsWith(`/api/v1/users/${USER_ID}/deactivate/`) &&
        method === "POST"
      ) {
        return ok({ ...USERS_PAGE.results[0], active: false });
      }
      if (url.split("?")[0].endsWith("/api/v1/users/")) return ok(USERS_PAGE);
      if (url.split("?")[0].endsWith("/api/v1/roles/")) return ok(ROLE_PAGE);
      return ok(EMPTY_PAGE);
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    renderAt("/admin/users");
    const row = await screen
      .findByRole("cell", { name: "ward-nurse" })
      .then((cell) => cell.closest("tr"));
    if (row === null) throw new Error("user row not found");

    await userEvent.click(within(row).getByRole("button", { name: "Deactivate" }));
    // Refused confirmation ⇒ no request leaves the browser.
    expect(findCalls(calls, `/api/v1/users/${USER_ID}/deactivate/`, "POST")).toHaveLength(0);

    confirmSpy.mockReturnValue(true);
    await userEvent.click(within(row).getByRole("button", { name: "Deactivate" }));
    await awaitCall(calls, `/api/v1/users/${USER_ID}/deactivate/`, "POST");
  });
});

describe("Roles", () => {
  it("saves the permission matrix and invalidates the roles list", async () => {
    const calls = stubFetch((url, method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(session());
      if (url.split("?")[0].endsWith(`/api/v1/roles/${ROLE_ID}/`) && method === "PATCH") {
        return ok(role({ permissions: ["identity.users.manage", "identity.roles.write"] }));
      }
      if (url.split("?")[0].endsWith("/api/v1/roles/")) return ok(ROLE_PAGE);
      return ok(EMPTY_PAGE);
    });

    renderAt("/admin/roles");
    const row = await screen
      .findByRole("cell", { name: "Tenant admin" })
      .then((cell) => cell.closest("tr"));
    if (row === null) throw new Error("role row not found");
    await userEvent.click(within(row).getByRole("button", { name: "Edit" }));

    const matrix = await screen.findByRole("region", { name: "Permission matrix" });
    expect(within(matrix).getByLabelText("identity.users.manage")).toBeChecked();
    await userEvent.click(within(matrix).getByLabelText("identity.roles.write"));
    await userEvent.click(within(matrix).getByRole("button", { name: "Save role" }));

    const patch = await awaitCall(calls, `/api/v1/roles/${ROLE_ID}/`, "PATCH");
    expect(parsedBody(patch)).toMatchObject({
      permissions: expect.arrayContaining([
        "identity.users.manage",
        "identity.roles.write",
      ]),
    });
    // The save invalidates ["roles", tenantId] — the walk re-runs.
    await waitFor(() =>
      expect(findCalls(calls, "/api/v1/roles/", "GET").length).toBeGreaterThanOrEqual(2),
    );
  });

  it("renders the matrix read-only when the session lacks identity.roles.write", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/"))
        return ok(session({ permissions: ["identity.users.manage"] }));
      if (url.split("?")[0].endsWith("/api/v1/roles/")) return ok(ROLE_PAGE);
      return ok(EMPTY_PAGE);
    });

    renderAt("/admin/roles");
    const row = await screen
      .findByRole("cell", { name: "Tenant admin" })
      .then((cell) => cell.closest("tr"));
    if (row === null) throw new Error("role row not found");
    await userEvent.click(within(row).getByRole("button", { name: "View" }));

    const matrix = await screen.findByRole("region", { name: "Permission matrix" });
    expect(within(matrix).getByLabelText("identity.users.manage")).toBeDisabled();
    expect(within(matrix).getByLabelText("identity.roles.write")).toBeDisabled();
    expect(
      within(matrix).queryByRole("button", { name: "Save role" }),
    ).not.toBeInTheDocument();
  });

  it("disables platform-scope codes and marks them as such", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(session());
      if (url.split("?")[0].endsWith("/api/v1/roles/")) return ok(ROLE_PAGE);
      return ok(EMPTY_PAGE);
    });

    renderAt("/admin/roles");
    const row = await screen
      .findByRole("cell", { name: "Tenant admin" })
      .then((cell) => cell.closest("tr"));
    if (row === null) throw new Error("role row not found");
    await userEvent.click(within(row).getByRole("button", { name: "Edit" }));

    const matrix = await screen.findByRole("region", { name: "Permission matrix" });
    // RoleSerializer refuses platform.* on tenant roles — a live toggle here
    // would be a control that can only ever 400.
    expect(within(matrix).getByLabelText("platform.tenants.manage")).toBeDisabled();
    expect(within(matrix).getByText(/platform-scope/i)).toBeInTheDocument();
  });

  it("offers the quality catalogue code as a grantable toggle (ninth backend-enforced code)", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(session());
      if (url.split("?")[0].endsWith("/api/v1/roles/")) return ok(ROLE_PAGE);
      return ok(EMPTY_PAGE);
    });

    renderAt("/admin/roles");
    const row = await screen
      .findByRole("cell", { name: "Tenant admin" })
      .then((cell) => cell.closest("tr"));
    if (row === null) throw new Error("role row not found");
    await userEvent.click(within(row).getByRole("button", { name: "Edit" }));

    const matrix = await screen.findByRole("region", { name: "Permission matrix" });
    // quality.catalogue.manage (quality_os/views.py:28, :35, :42, :49) is
    // enforced and — unlike platform.* — accepted on tenant roles, so the
    // matrix must recommend it as a live toggle; the fixture role carries
    // no extra codes, so a rendered toggle can only come from the
    // recommended vocabulary.
    const toggle = within(matrix).getByLabelText("quality.catalogue.manage");
    expect(toggle).toBeEnabled();
  });
});

describe("DepartmentsWardsBeds", () => {
  it("edits a department and deactivates it through PATCH", async () => {
    const calls = stubFetch((url, method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(session());
      if (
        url.split("?")[0].endsWith(`/api/v1/departments/${DEPARTMENT_ID}/`) &&
        method === "PATCH"
      ) {
        return ok({ ...DEPARTMENT, active: false });
      }
      if (url.split("?")[0].endsWith("/api/v1/departments/")) {
        return ok({ count: 1, next: null, previous: null, results: [DEPARTMENT] });
      }
      return ok(EMPTY_PAGE);
    });

    renderAt("/admin/departments");
    const row = await screen
      .findByRole("cell", { name: "General Medicine" })
      .then((cell) => cell.closest("tr"));
    if (row === null) throw new Error("department row not found");
    await userEvent.click(within(row).getByRole("button", { name: "Edit" }));

    const panel = await screen.findByRole("region", { name: "Edit department" });
    expect(within(panel).getByLabelText(/department name/i)).toHaveValue("General Medicine");
    await userEvent.click(within(panel).getByLabelText("Active"));
    await userEvent.click(within(panel).getByRole("button", { name: "Save department" }));

    const patch = await awaitCall(
      calls,
      `/api/v1/departments/${DEPARTMENT_ID}/`,
      "PATCH",
    );
    expect(parsedBody(patch)).toMatchObject({
      name: "General Medicine",
      active: false,
    });
    // Deactivation keeps the row (SET-011) — the list refetch shows it marked inactive.
    await waitFor(() =>
      expect(findCalls(calls, "/api/v1/departments/", "GET").length).toBeGreaterThanOrEqual(
        2,
      ),
    );
  });

  it("edits a bed and never sends the occupied flag", async () => {
    const calls = stubFetch((url, method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(session());
      if (url.split("?")[0].endsWith(`/api/v1/beds/${BED_ID}/`) && method === "PATCH") {
        return ok({ ...BED, functional: false });
      }
      if (url.split("?")[0].endsWith("/api/v1/beds/")) {
        return ok({ count: 1, next: null, previous: null, results: [BED] });
      }
      if (url.split("?")[0].endsWith("/api/v1/wards/")) {
        return ok({ count: 1, next: null, previous: null, results: [WARD] });
      }
      return ok(EMPTY_PAGE);
    });

    renderAt("/admin/wards-beds");
    expect(await screen.findByRole("region", { name: "Wards" })).toBeInTheDocument();
    const row = await screen
      .findByRole("cell", { name: "B-01" })
      .then((cell) => cell.closest("tr"));
    if (row === null) throw new Error("bed row not found");
    await userEvent.click(within(row).getByRole("button", { name: "Edit" }));

    const panel = await screen.findByRole("region", { name: "Edit bed" });
    await userEvent.click(within(panel).getByLabelText("Functional"));
    await userEvent.click(within(panel).getByRole("button", { name: "Save bed" }));

    const patch = await awaitCall(calls, `/api/v1/beds/${BED_ID}/`, "PATCH");
    // Occupancy is live clinical state owned by admissions — the serializer
    // would accept it, so the UI must simply never carry it (design.md §7:
    // "occupancy cannot be silently cleared").
    expect("occupied" in parsedBody(patch)).toBe(false);
    expect(parsedBody(patch)).toMatchObject({
      bed_number: "B-01",
      functional: false,
      active: true,
    });
  });
});

describe("AuditLog", () => {
  it("drill-down: issues the filtered request from the URL and shows only matching rows", async () => {
    const calls = stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(session());
      if (url.split("?")[0].endsWith("/api/v1/audit-log/")) {
        const params = new URLSearchParams(url.split("?")[1] ?? "");
        if (
          params.get("entity_type") === "registry.patient" &&
          params.get("entity_id") === PATIENT_ID
        ) {
          return ok({
            count: 1,
            next: null,
            previous: null,
            results: [auditEvent()],
          });
        }
        return ok({
          count: 2,
          next: null,
          previous: null,
          results: [
            auditEvent(),
            auditEvent({
              id: "c0c0c0c0-0000-4000-8000-00000000c0c2",
              entity_type: "identity.department",
              entity_id: DEPARTMENT_ID,
            }),
          ],
        });
      }
      return ok(EMPTY_PAGE);
    });

    renderAt(`/admin/audit?entity_type=registry.patient&entity_id=${PATIENT_ID}`);
    // Await a data row (not the region shell) so the whole session→audit
    // fetch chain resolves inside one act window.
    expect(
      await screen.findByRole("cell", { name: `registry.patient ${PATIENT_ID}` }),
    ).toBeInTheDocument();
    const list = screen.getByRole("region", { name: "Audit log" });
    const auditCall = await awaitCall(calls, "/api/v1/audit-log/", "GET");
    expect(auditCall.url).toContain("entity_type=registry.patient");
    expect(auditCall.url).toContain(`entity_id=${PATIENT_ID}`);

    expect(
      await within(list).findByRole("cell", { name: `registry.patient ${PATIENT_ID}` }),
    ).toBeInTheDocument();
    expect(
      within(list).queryByRole("cell", {
        name: `identity.department ${DEPARTMENT_ID}`,
      }),
    ).not.toBeInTheDocument();
    // The URL's filter values are the inputs' values — the link is shareable.
    expect(screen.getByLabelText(/entity type/i)).toHaveValue("registry.patient");
    expect(screen.getByLabelText(/entity id/i)).toHaveValue(PATIENT_ID);
    // Actor and action are identifiers only (the PHI rule: no names).
    expect(within(list).getByRole("cell", { name: USER_ID })).toBeInTheDocument();
    expect(within(list).getByRole("cell", { name: "read" })).toBeInTheDocument();
  });

  it("clicking a row's drill-down narrows the table to that entity", async () => {
    let filtered = false;
    stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(session());
      if (url.split("?")[0].endsWith("/api/v1/audit-log/")) {
        const params = new URLSearchParams(url.split("?")[1] ?? "");
        if (params.get("entity_id") === PATIENT_ID) {
          filtered = true;
          return ok({
            count: 1,
            next: null,
            previous: null,
            results: [auditEvent()],
          });
        }
        return ok({
          count: 2,
          next: null,
          previous: null,
          results: [
            auditEvent(),
            auditEvent({
              id: "c0c0c0c0-0000-4000-8000-00000000c0c2",
              entity_type: "identity.department",
              entity_id: DEPARTMENT_ID,
            }),
          ],
        });
      }
      return ok(EMPTY_PAGE);
    });

    renderAt("/admin/audit");
    expect(
      await screen.findByRole("cell", {
        name: `identity.department ${DEPARTMENT_ID}`,
      }),
    ).toBeInTheDocument();
    const list = screen.getByRole("region", { name: "Audit log" });

    const row = rowOf(`registry.patient ${PATIENT_ID}`);
    await userEvent.click(within(row).getByRole("button", { name: "Drill down" }));

    expect(
      await within(list).findByRole("cell", { name: `registry.patient ${PATIENT_ID}` }),
    ).toBeInTheDocument();
    await waitFor(() => expect(filtered).toBe(true));
    expect(
      within(list).queryByRole("cell", {
        name: `identity.department ${DEPARTMENT_ID}`,
      }),
    ).not.toBeInTheDocument();
  });

  it("carries the entity filters into the page-2 request (pagination composes with filters)", async () => {
    const calls = stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(session());
      if (url.split("?")[0].endsWith("/api/v1/audit-log/")) {
        const params = new URLSearchParams(url.split("?")[1] ?? "");
        const filtered =
          params.get("entity_type") === "registry.patient" &&
          params.get("entity_id") === PATIENT_ID;
        return ok({
          count: 51,
          // Only page 1 of the filtered view offers a next page — the Pager
          // button must be enabled by data, not assumption.
          next:
            filtered && params.get("page") === "1"
              ? "http://localhost/api/v1/audit-log/?page=2"
              : null,
          previous: null,
          results: [auditEvent()],
        });
      }
      return ok(EMPTY_PAGE);
    });

    renderAt(`/admin/audit?entity_type=registry.patient&entity_id=${PATIENT_ID}`);
    expect(
      await screen.findByRole("cell", { name: `registry.patient ${PATIENT_ID}` }),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));

    const page2 = await vi.waitUntil(() =>
      calls.find(
        (c) =>
          c.method === "GET" &&
          c.url.split("?")[0].endsWith("/api/v1/audit-log/") &&
          c.url.includes("page=2"),
      ),
    );
    if (page2 === undefined) throw new Error("no page-2 audit request");
    // Dropping the filters on page 2 would silently widen the view from one
    // entity to every row of every entity the tenant ever audited.
    expect(page2.url).toContain("entity_type=registry.patient");
    expect(page2.url).toContain(`entity_id=${PATIENT_ID}`);
  });
});

describe("PatientDetail audit entry point (AUD-003)", () => {
  it("links to the audit drill-down with the patient's entity filters prefilled", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(session());
      if (url.endsWith(`/api/v1/patients/${PATIENT_ID}/`)) return ok(patient());
      return ok(EMPTY_PAGE);
    });

    renderAt(`/patients/${PATIENT_ID}`);
    expect(
      await screen.findByRole("heading", { name: "UHID-202610-000001" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view access history/i })).toHaveAttribute(
      "href",
      `/admin/audit?entity_type=registry.patient&entity_id=${PATIENT_ID}`,
    );
  });
});

describe("BreakGlassDialog", () => {
  it("keeps submit disabled until the reason is non-empty, then posts the header and body and shows the grant", async () => {
    const calls = stubFetch((url, method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(session());
      if (url.endsWith("/api/v1/auth/break-glass/") && method === "POST") {
        return created({
          access_id: "0d0d0d0d-0000-4000-8000-000000000d0d",
          granted_at: "2026-10-21T06:00:00Z",
        });
      }
      return ok(EMPTY_PAGE);
    });

    renderDialog();
    // The claim gate reads the session query — the dialog renders nothing
    // until it resolves, so the reason field is the readiness signal.
    await screen.findByLabelText(/reason/i);
    const submit = screen.getByRole("button", { name: /grant emergency access/i });
    expect(submit).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/reason/i), "  ");
    // Whitespace is empty to the server (it strips) — still blocked.
    expect(submit).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/reason/i), "Unconscious patient, no assigned scope");
    expect(submit).toBeEnabled();
    await userEvent.click(submit);

    const grantCall = await awaitCall(calls, "/api/v1/auth/break-glass/", "POST");
    // The schema trims the reason exactly as the server would (it strips the
    // header value before its emptiness check), so the wire carries the
    // trimmed text either way.
    expect(grantCall.headers["x-break-glass-reason"]).toBe(
      "Unconscious patient, no assigned scope",
    );
    expect(parsedBody(grantCall)).toMatchObject({
      resource_type: "registry.patient",
      resource_id: PATIENT_ID,
    });

    const status = await screen.findByRole("status");
    expect(
      within(status).getByText("0d0d0d0d-0000-4000-8000-000000000d0d"),
    ).toBeInTheDocument();
    expect(within(status).getByText("2026-10-21T06:00:00Z")).toBeInTheDocument();
  });

  it("renders the server's refusal detail when the role holds no break-glass claim (403)", async () => {
    stubFetch((url, method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(session());
      if (url.endsWith("/api/v1/auth/break-glass/") && method === "POST") {
        return jsonResponse(403, {
          detail: "This role does not hold break-glass access.",
        });
      }
      return ok(EMPTY_PAGE);
    });

    renderDialog();
    await screen.findByLabelText(/reason/i);
    await userEvent.type(screen.getByLabelText(/reason/i), "Emergency review");
    await userEvent.click(screen.getByRole("button", { name: /grant emergency access/i }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This role does not hold break-glass access.");
  });

  it("renders nothing when the session holds no break-glass claim", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/"))
        return ok(session({ allows_break_glass: false }));
      return ok(EMPTY_PAGE);
    });

    renderDialog();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /grant emergency access/i })).not.toBeInTheDocument(),
    );
  });

  it("mounts the emergency-access trigger on the patient profile only with the claim", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/"))
        return ok(session({ allows_break_glass: false }));
      if (url.endsWith(`/api/v1/patients/${PATIENT_ID}/`)) return ok(patient());
      return ok(EMPTY_PAGE);
    });

    renderAt(`/patients/${PATIENT_ID}`);
    await screen.findByRole("heading", { name: "UHID-202610-000001" });
    expect(
      screen.queryByRole("button", { name: /emergency access/i }),
    ).not.toBeInTheDocument();

    cleanup();
    vi.unstubAllGlobals();
    stubFetch((u) => {
      if (u.endsWith("/api/v1/auth/me/")) return ok(session());
      if (u.endsWith(`/api/v1/patients/${PATIENT_ID}/`)) return ok(patient());
      return ok(EMPTY_PAGE);
    });
    renderAt(`/patients/${PATIENT_ID}`);
    expect(
      await screen.findByRole("button", { name: /emergency access/i }),
    ).toBeInTheDocument();
  });
});
