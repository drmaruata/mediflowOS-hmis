/**
 * Patient registry integration tests (REG-001..007, UI-002).
 *
 * Pins the contract the backend already enforces: the create action mints
 * the UHID server-side (REG-001 — the client never sends or pre-fills one),
 * the duplicate check is an advisory pre-submit probe (REG-003) whose
 * "register anyway" needs an explicit confirm, the verification queue mixes
 * pending registrations with ABDM multi-candidate rows (ABD-009) whose
 * verify action only accepts pending patients, and search goes through the
 * search action with REG-008's exact-digest degradation stated on screen
 * rather than mystified.
 *
 * The screens mount under the module's real route table (MemoryRouter), and
 * every query is tenant-scoped by the session — the cross-tenant tests stub
 * a foreign row and assert it can never render, which is the client-side
 * half of the tenant guarantee (the server's RLS scoping is the other half).
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PatientDetail from "./PatientDetail";
import PatientList from "./PatientList";
import PatientRegistration from "./PatientRegistration";
import VerificationQueue from "./VerificationQueue";
import { useAuthStore } from "@/stores/authStore";
import type { Patient } from "./patient.api";

const jsonResponse = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const ok = (body: unknown): Response => jsonResponse(200, body);
const created = (body: unknown): Response => jsonResponse(201, body);

const TENANT = "aaaaaaaa-0000-0000-0000-0000000000a1";
const FOREIGN_TENANT = "bbbbbbbb-0000-0000-0000-0000000000b2";

const SESSION = {
  username: "clerk-a",
  tenant_id: TENANT,
  facility_id: null,
  role: "clerk",
  permissions: [],
  allows_break_glass: false,
  requires_mfa: false,
  mfa_verified: true,
};

const DEPT_ID = "22222222-2222-4222-8222-222222222222";
const PATIENT_ID = "11111111-1111-4111-8111-111111111111";
const PENDING_ID = "33333333-3333-4333-8333-333333333333";
const AMBIGUOUS_ID = "44444444-4444-4444-8444-444444444444";
const FOREIGN_ID = "55555555-5555-4555-8555-555555555555";

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

const DEPARTMENT_PAGE = {
  count: 1,
  next: null,
  previous: null,
  results: [{ id: DEPT_ID, name: "General Medicine" }],
};

interface RecordedCall {
  url: string;
  method: string;
  body: string | null;
}

/** Stub global fetch, record every call, and route by URL + method. */
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

const findCall = (calls: RecordedCall[], url: string, method: string) =>
  calls.find((c) => c.url.split("?")[0].endsWith(url) && c.method === method);

/** The create POST is /patients/ exactly — the duplicate-check probe shares the prefix but not the path. */
const findCreateCall = (calls: RecordedCall[]) =>
  calls.find(
    (c) =>
      c.url.split("?")[0].endsWith("/api/v1/patients/") && c.method === "POST",
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
  const call = await vi.waitUntil(() => findCall(calls, url, method));
  if (call === undefined) throw new Error(`expected a ${method} ${url} call`);
  return call;
};

const parsedBody = (call: RecordedCall): Record<string, unknown> =>
  JSON.parse(call.body ?? "{}") as Record<string, unknown>;

/** Mount the module's four screens under their real route paths. */
function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/patients" element={<PatientList />} />
          <Route path="/patients/register" element={<PatientRegistration />} />
          <Route
            path="/patients/verification-queue"
            element={<VerificationQueue />}
          />
          <Route path="/patients/:id" element={<PatientDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const rowOf = (cellText: string | RegExp) => {
  const row = screen.getByRole("cell", { name: cellText }).closest("tr");
  if (row === null) throw new Error(`no table row for ${String(cellText)}`);
  return row;
};

async function fillIdentity(name: string, gender: string, dob: string) {
  await userEvent.type(screen.getByLabelText(/patient name/i), name);
  await userEvent.selectOptions(screen.getByLabelText(/gender/i), gender);
  fireEvent.change(screen.getByLabelText(/date of birth/i), {
    target: { value: dob },
  });
}

/** The OPD card's address and contact number are both required. */
async function fillContact(address: string, mobile: string) {
  await userEvent.type(screen.getByLabelText(/address/i), address);
  await userEvent.type(screen.getByLabelText(/contact number/i), mobile);
}

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
});

describe("PatientRegistration", () => {
  it("registers a patient and renders the server-minted UHID and token, never a client-entered one", async () => {
    const calls = stubFetch((url, method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.includes("/api/v1/departments/")) return ok(DEPARTMENT_PAGE);
      if (url.endsWith("/api/v1/patients/duplicate-check/") && method === "POST") {
        return ok({ warn: false, candidates: [] });
      }
      if (url.split("?")[0].endsWith("/api/v1/patients/") && method === "POST") {
        return created({
          ...patient(),
          uhid: "UHID-202610-000042",
          token: { series: "A", number: 14 },
          visit_id: "vvvvvvvv-vvvv-4vvv-8vvv-vvvvvvvvvvvv",
        });
      }
      return ok([]);
    });

    renderAt("/patients/register");
    await screen.findByRole("option", { name: "General Medicine" });

    await fillIdentity("Asha Lakshmi", "female", "1984-03-12");
    // The age is derived from the DoB and shown read-only — it fills itself.
    expect(
      screen.getByLabelText<HTMLInputElement>(/age/i).value,
    ).toMatch(/^\d{1,3}$/);
    fireEvent.blur(screen.getByLabelText(/date of birth/i));
    await fillContact("12 MG Road, Mysuru", "9876543210");
    await userEvent.selectOptions(
      screen.getByLabelText(/department/i),
      DEPT_ID,
    );
    await userEvent.click(screen.getByRole("button", { name: /register patient/i }));

    const createCall = await vi.waitUntil(() => findCreateCall(calls));
    if (createCall === undefined) throw new Error("no create POST");
    const body = parsedBody(createCall);
    // REG-001: the UHID is minted by the server; the wire payload never carries one.
    expect("uhid" in body).toBe(false);
    expect(body).toMatchObject({
      demographics: { name: "Asha Lakshmi", gender: "female", dob: "1984-03-12" },
      address: { full: "12 MG Road, Mysuru" },
      contact: { mobile: "9876543210" },
      intake_department_id: DEPT_ID,
      intake_channel: "counter",
    });

    const success = await screen.findByRole("status");
    expect(within(success).getByText("UHID-202610-000042")).toBeInTheDocument();
    expect(within(success).getByText("A-14")).toBeInTheDocument();
    // The print screen IS available (Task 36) — success panel links to it.
    expect(
      within(success).getByText(/OP slip ready — click "Print OP slip" to open the print view\./i),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /print op slip/i })).toBeInTheDocument();
  });

  it("warns about probable duplicates on blur and requires an explicit register-anyway confirm", async () => {
    const calls = stubFetch((url, method, body) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.includes("/api/v1/departments/")) return ok(DEPARTMENT_PAGE);
      if (url.endsWith("/api/v1/patients/duplicate-check/") && method === "POST") {
        // Name alone cannot birth-match (find_duplicates needs a year), so the
        // probe only warns once a date of birth is part of the candidate.
        if (body?.dob) {
          return ok({
            warn: true,
            candidates: [
              {
                id: "99999999-9999-4999-8999-999999999999",
                uhid: "UHID-202609-000017",
                name: "Asha Lakshmi",
                gender: "female",
                year_of_birth: 1984,
                mobile_masked: "******3210",
              },
            ],
          });
        }
        return ok({ warn: false, candidates: [] });
      }
      if (url.split("?")[0].endsWith("/api/v1/patients/") && method === "POST") {
        return created(patient({ uhid: "UHID-202610-000043" }));
      }
      return ok([]);
    });

    renderAt("/patients/register");
    await screen.findByRole("option", { name: "General Medicine" });

    await fillIdentity("Asha Lakshmi", "female", "1984-03-12");
    fireEvent.blur(screen.getByLabelText(/date of birth/i));

    // The name blur (when focus left for the gender select) already probed
    // with the name alone; the DOB blur is the probe that must carry both.
    const probes = await vi.waitUntil(() =>
      calls.filter(
        (c) =>
          c.url.endsWith("/api/v1/patients/duplicate-check/") &&
          c.method === "POST",
      ).length >= 2
        ? calls.filter(
            (c) =>
              c.url.endsWith("/api/v1/patients/duplicate-check/") &&
              c.method === "POST",
          )
        : undefined,
    );
    expect(parsedBody(probes[probes.length - 1])).toMatchObject({
      name: "Asha Lakshmi",
      dob: "1984-03-12",
    });
    await screen.findByRole("alert", { name: "Possible duplicates" });
    expect(screen.getByText("UHID-202609-000017")).toBeInTheDocument();

    await fillContact("12 MG Road, Mysuru", "9876543210");
    await userEvent.selectOptions(
      screen.getByLabelText(/department/i),
      DEPT_ID,
    );

    // Without the confirm, the register attempt is refused — no create POST.
    await userEvent.click(screen.getByRole("button", { name: /register patient/i }));
    expect(
      screen.getByText(/check the box to register anyway/i),
    ).toBeInTheDocument();
    expect(findCreateCall(calls)).toBeUndefined();

    await userEvent.click(screen.getByLabelText(/register anyway/i));
    await userEvent.click(screen.getByRole("button", { name: /register patient/i }));

    await vi.waitUntil(() => findCreateCall(calls) !== undefined);
    expect(await screen.findByText("UHID-202610-000043")).toBeInTheDocument();
  });

  it("blocks an empty submit, shows the required errors and focuses the first invalid field", async () => {
    const calls = stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.includes("/api/v1/departments/")) return ok(DEPARTMENT_PAGE);
      return ok([]);
    });

    renderAt("/patients/register");
    await screen.findByRole("option", { name: "General Medicine" });

    await userEvent.click(screen.getByRole("button", { name: /register patient/i }));

    // REG-007's required set is visible field-by-field, nothing posts, and
    // RHF's default shouldFocusError puts the first invalid control in focus.
    expect(screen.getByText(/enter the patient's full name\./i)).toBeInTheDocument();
    expect(
      screen.getByText(/enter the patient's date of birth\./i),
    ).toBeInTheDocument();
    expect(screen.getByText(/enter the patient's address\./i)).toBeInTheDocument();
    expect(
      screen.getByText(/enter the patient's contact number\./i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/select the OP intake department\./i),
    ).toBeInTheDocument();
    expect(findCreateCall(calls)).toBeUndefined();
    await waitFor(() =>
      expect(screen.getByLabelText(/patient name/i)).toHaveFocus(),
    );
  });

  it("blocks the save and focuses the department when none is selected", async () => {
    const calls = stubFetch((url, method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.includes("/api/v1/departments/")) return ok(DEPARTMENT_PAGE);
      if (url.endsWith("/api/v1/patients/duplicate-check/") && method === "POST") {
        return ok({ warn: false, candidates: [] });
      }
      return ok([]);
    });

    renderAt("/patients/register");
    await fillIdentity("Ravi Kumar", "male", "1980-01-02");
    await fillContact("4 Church Street, Chennai", "9876543210");

    await userEvent.click(screen.getByRole("button", { name: /register patient/i }));
    await waitFor(() =>
      expect(screen.getByLabelText(/department/i)).toHaveFocus(),
    );
    expect(findCreateCall(calls)).toBeUndefined();
  });
});

describe("VerificationQueue", () => {
  it("lists pending and ambiguous patients, verify removes a pending one, and a foreign tenant's row never renders", async () => {
    let queue = [
      patient({
        id: PENDING_ID,
        uhid: "UHID-202610-000010",
        demographics: { name: "Pending Patil", gender: "male", dob: "1990-07-01" },
      }),
      patient({
        id: AMBIGUOUS_ID,
        uhid: "UHID-202610-000011",
        verification_status: "ambiguous",
        demographics: { name: "Ambiguous Amina", gender: "female", dob: "1979-02-02" },
      }),
      patient({
        id: FOREIGN_ID,
        tenant_id: FOREIGN_TENANT,
        uhid: "UHID-202610-000012",
        demographics: { name: "Other Hospital Om", gender: "male", dob: "1965-04-04" },
      }),
    ];
    const calls = stubFetch((url, method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.endsWith("/api/v1/patients/verification_queue/")) {
        return ok(queue.map((row) => ({ ...row })));
      }
      if (url.endsWith(`/api/v1/patients/${PENDING_ID}/verify/`) && method === "POST") {
        queue = queue.filter((row) => row.id !== PENDING_ID);
        return ok(patient({ id: PENDING_ID, verification_status: "verified" }));
      }
      return ok([]);
    });

    renderAt("/patients/verification-queue");
    const list = await screen.findByRole("region", { name: "Verification queue" });
    expect(
      await within(list).findByRole("cell", { name: "UHID-202610-000010" }),
    ).toBeInTheDocument();
    expect(within(list).getByRole("cell", { name: "UHID-202610-000011" })).toBeInTheDocument();
    // The foreign row never renders even though the stubbed API returned it.
    expect(screen.queryByText("Other Hospital Om")).not.toBeInTheDocument();
    // Landmarks are role-queryable (UI-002).
    expect(screen.getByRole("button", { name: "Refresh now" })).toBeInTheDocument();

    // Ambiguous rows are ABDM multi-candidate entries: an honest state, no
    // dead verify button (the endpoint refuses them with 400).
    const ambiguousRow = rowOf("UHID-202610-000011");
    expect(within(ambiguousRow).queryByRole("button", { name: /verify/i })).toBeNull();
    expect(within(ambiguousRow).getByText(/ABDM matched several/i)).toBeInTheDocument();

    const pendingRow = rowOf("UHID-202610-000010");
    await userEvent.click(
      within(pendingRow).getByRole("button", { name: "Verify" }),
    );
    await awaitCall(calls, `/api/v1/patients/${PENDING_ID}/verify/`, "POST");
    await waitFor(() =>
      expect(
        within(list).queryByRole("cell", { name: "UHID-202610-000010" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("surfaces the server's 400 when the row was verified by another clerk first", async () => {
    stubFetch((url, method) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.endsWith("/api/v1/patients/verification_queue/")) {
        return ok([
          patient({
            id: PENDING_ID,
            uhid: "UHID-202610-000010",
            demographics: { name: "Pending Patil", gender: "male", dob: "1990-07-01" },
          }),
        ]);
      }
      if (url.endsWith(`/api/v1/patients/${PENDING_ID}/verify/`) && method === "POST") {
        return jsonResponse(400, {
          detail: "Patient is not pending verification.",
        });
      }
      return ok([]);
    });

    renderAt("/patients/verification-queue");
    const row = await screen.findByRole("cell", { name: "UHID-202610-000010" }).then(
      (cell) => cell.closest("tr"),
    );
    if (row === null) throw new Error("pending row not found");
    await userEvent.click(within(row).getByRole("button", { name: "Verify" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Patient is not pending verification.");
  });
});

describe("PatientList", () => {
  it("searches through the search action and states the exact-match degradation", async () => {
    const calls = stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.split("?")[0].endsWith("/api/v1/patients/search/")) {
        const q = new URLSearchParams(url.split("?")[1] ?? "").get("q");
        return ok(q === "Asha" ? [patient()] : []);
      }
      if (url.includes("/api/v1/patients/?registered_on=")) {
        return ok({ count: 0, next: null, previous: null, results: [] });
      }
      return ok([]);
    });

    renderAt("/patients");
    await screen.findByRole("heading", { name: "Patients" });

    await userEvent.type(screen.getByLabelText(/search patients/i), "Asha");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    const searchCall = await awaitCall(
      calls,
      "/api/v1/patients/search/",
      "GET",
    );
    expect(searchCall.url).toContain("q=Asha");
    expect(await screen.findByRole("cell", { name: "UHID-202610-000001" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute(
      "href",
      `/patients/${PATIENT_ID}`,
    );

    // A mobile fragment deliberately matches nothing (REG-008: identifiers
    // are ciphertext, only exact digests are indexed) — the empty state says
    // so instead of leaving a silent no-match.
    await userEvent.clear(screen.getByLabelText(/search patients/i));
    await userEvent.type(screen.getByLabelText(/search patients/i), "9876");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText(/match the complete number only/i)).toBeInTheDocument();
    expect(screen.queryByText("Asha Lakshmi")).not.toBeInTheDocument();
  });

  it("never renders another tenant's rows", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.split("?")[0].endsWith("/api/v1/patients/search/")) {
        return ok([
          patient({
            tenant_id: FOREIGN_TENANT,
            demographics: { name: "Other Hospital Om", gender: "male" },
          }),
        ]);
      }
      if (url.includes("/api/v1/patients/?registered_on=")) {
        return ok({ count: 0, next: null, previous: null, results: [] });
      }
      return ok([]);
    });

    renderAt("/patients");
    await userEvent.type(screen.getByLabelText(/search patients/i), "Other");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText(/no patients match/i)).toBeInTheDocument();
    expect(screen.queryByText("Other Hospital Om")).not.toBeInTheDocument();
  });

  it("lists the day's registrations by default, no search needed", async () => {
    const calls = stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.includes("/api/v1/patients/?registered_on=")) {
        return ok({ count: 1, next: null, previous: null, results: [patient()] });
      }
      return ok([]);
    });

    renderAt("/patients");
    await screen.findByRole("heading", { name: "Patients" });

    const rosterCall = await awaitCall(calls, "/api/v1/patients/", "GET");
    expect(rosterCall.url).toContain("registered_on=");
    // The local calendar day (YYYY-MM-DD) is what the backend filters on —
    // never `toISOString()`, whose UTC day can differ near local midnight.
    const day = rosterCall.url.split("registered_on=")[1]?.split("&")[0] ?? "";
    expect(day).toMatch(/^\d{4}-\d{2}-\d{2}$/);

    expect(
      await screen.findByRole("cell", { name: "UHID-202610-000001" }),
    ).toBeInTheDocument();
  });

  it("walks every page so a busy day's roster is not truncated", async () => {
    const overflow = patient({
      id: "66666666-6666-4666-8666-666666666666",
      uhid: "UHID-202610-000002",
      demographics: { name: "Ravi Kumar", gender: "male", dob: "1980-01-02" },
    });
    stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.includes("/api/v1/patients/?registered_on=")) {
        const page = new URLSearchParams(url.split("?")[1] ?? "").get("page");
        return page === "2"
          ? ok({ count: 2, next: null, previous: null, results: [overflow] })
          : ok({
              count: 2,
              // DRF's `next` is absolute; the client strips the origin.
              next: `${window.location.origin}${url}&page=2`,
              previous: null,
              results: [patient()],
            });
      }
      return ok([]);
    });

    renderAt("/patients");
    await screen.findByRole("heading", { name: "Patients" });

    expect(
      await screen.findByRole("cell", { name: "UHID-202610-000001" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("cell", { name: "UHID-202610-000002" }),
    ).toBeInTheDocument();
  });

  it("never renders another tenant's day roster", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.includes("/api/v1/patients/?registered_on=")) {
        return ok({
          count: 1,
          next: null,
          previous: null,
          results: [
            patient({
              tenant_id: FOREIGN_TENANT,
              demographics: {
                name: "Other Hospital Om",
                gender: "male",
                dob: "1984-03-12",
              },
            }),
          ],
        });
      }
      return ok([]);
    });

    renderAt("/patients");
    await screen.findByRole("heading", { name: "Patients" });

    expect(
      await screen.findByText(/no patients registered yet today/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("Other Hospital Om")).not.toBeInTheDocument();
  });

  it("states when the day's roster cannot load", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.includes("/api/v1/patients/?registered_on=")) {
        return jsonResponse(500, { detail: "boom" });
      }
      return ok([]);
    });

    renderAt("/patients");
    await screen.findByRole("heading", { name: "Patients" });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /boom|could not be loaded/i,
    );
  });
});

describe("PatientDetail", () => {
  it("shows the record's demographics with its verification state", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/v1/auth/me/")) return ok(SESSION);
      if (url.endsWith(`/api/v1/patients/${PATIENT_ID}/`)) return ok(patient());
      return ok([]);
    });

    renderAt(`/patients/${PATIENT_ID}`);

    expect(
      await screen.findByRole("heading", { name: "UHID-202610-000001" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Asha Lakshmi")).toBeInTheDocument();
    expect(screen.getByText("Pending verification")).toBeInTheDocument();
    expect(screen.getByText("9876543210")).toBeInTheDocument();
  });
});
