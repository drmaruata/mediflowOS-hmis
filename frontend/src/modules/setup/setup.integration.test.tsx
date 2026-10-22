/**
 * Setup wizard integration tests (SET-001, SET-007, SET-008, SET-009).
 *
 * Pins the contract the backend already enforces in
 * tests/integration/test_setup_wizard.py: GET /setup/ is the orchestrated
 * ten-step spine (a step with no row still appears, pending and incomplete),
 * PUT /setup/{step_key}/ upserts one step, and resumption must land the
 * tenant administrator exactly where they stopped — the classic silent
 * failure this suite exists for is a wizard that forgets a completed step.
 *
 * Role-based queries double as accessibility assertions: the stepper is a
 * real list, step headings are h1/h2 landmarks, field errors associate with
 * their inputs, and load/permission failures render explicit alerts instead
 * of spinners or silent no-ops (UI-002, UI_UX §7).
 */

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SetupWizard from "./SetupWizard";
import { NAV_ITEMS } from "@/lib/navigation";

const jsonResponse = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const ok = (body: unknown): Response => jsonResponse(200, body);
const created = (body: unknown): Response => jsonResponse(201, body);

/** The backend's fixed DRF page size (settings/base.py PAGE_SIZE). */
const PAGE_SIZE = 50;

const SETUP_KEYS = [
  "hospital_identity",
  "ownership_level",
  "address",
  "abdm_hfr_ids",
  "accreditation",
  "departments_wards_beds",
  "service_units",
  "staff_positions",
  "reference_data",
  "indicators_baseline",
] as const;

type StepOverrides = Partial<
  Record<(typeof SETUP_KEYS)[number], { status: string; payload: Record<string, unknown> | null }>
>;

/** The orchestrated GET /setup/ body: all ten steps, defaults pending. */
function setupBody(overrides: StepOverrides = {}) {
  return SETUP_KEYS.map((key) => {
    const override = overrides[key];
    const status = override?.status ?? "pending";
    return {
      step_key: key,
      status,
      payload: override?.payload ?? null,
      complete: status === "complete",
      updated_at: null,
    };
  });
}

const FACILITY_ID = "11111111-1111-4111-8111-111111111111";
const DEPT_OPD_ID = "22222222-2222-4222-8222-222222222222";
const DEPT_IPD_ID = "33333333-3333-4333-8333-333333333333";
const WARD_ID = "44444444-4444-4444-8444-444444444444";

const FACILITY = {
  id: FACILITY_ID,
  tenant: "t",
  name: "Main Campus",
  level: "District Hospital",
  abdm_hip_id: null,
  abdm_facility_id: null,
  hfr_id: null,
  abdm_registration_status: "pending",
  address: null,
  created_at: "2026-01-01T00:00:00Z",
};

const DEPARTMENT_OPD = {
  id: DEPT_OPD_ID,
  tenant: "t",
  facility: FACILITY_ID,
  name: "OPD",
  opd_enabled: true,
  ipd_enabled: false,
  active: true,
  effective_from: "2026-01-01",
  effective_to: null,
};

const DEPARTMENT_IPD = {
  id: DEPT_IPD_ID,
  tenant: "t",
  facility: FACILITY_ID,
  name: "IPD",
  opd_enabled: false,
  ipd_enabled: true,
  active: true,
  effective_from: "2026-01-01",
  effective_to: null,
};

const WARD = {
  id: WARD_ID,
  tenant_id: "t",
  department: DEPT_OPD_ID,
  name: "General Ward",
  type_tag: "Medical",
  active: true,
};

/** 51 wards — the ward on page 2 is what the bed→ward join must still name. */
const MANY_WARDS = Array.from({ length: 51 }, (_, i) => ({
  id: `ward-${i + 1}`,
  tenant_id: "t",
  department: DEPT_OPD_ID,
  name: `Ward ${i + 1}`,
  type_tag: "Medical",
  active: true,
}));

/** 103 beds in ward-51 — past the 50-row page, the PRD's own "~100 beds" scale. */
const MANY_BEDS = Array.from({ length: 103 }, (_, i) => ({
  id: `bed-${i + 1}`,
  tenant: "t",
  ward: "ward-51",
  bed_number: `B-${i + 1}`,
  functional: true,
  active: true,
}));

interface RecordedCall {
  url: string;
  method: string;
  body: string | null;
}

/**
 * Stub fetch for the whole wizard surface. GET /setup/ serves `setup` (which
 * PUTs mutate, proving invalidation drives the refetch); the paginated CRUD
 * lists slice `lists` at the backend's fixed PAGE_SIZE the same way the real
 * paginator does (with an absolute `next`, like DRF's, for the page-walking
 * fetch-all to consume) and POSTs append to them, so an added row appears
 * the way production would render it — through the invalidation, not the
 * POST response. A list named in `failingPosts` answers every POST with a
 * non-field 500, the shape the alert tests must surface.
 */
function stubWizardFetch(
  setup: ReturnType<typeof setupBody>,
  lists: Record<string, Array<Record<string, unknown>>>,
  failingPosts: string[] = [],
) {
  const calls: RecordedCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({
        url,
        method,
        body: typeof init?.body === "string" ? init.body : null,
      });

      const putStep = url.match(/\/api\/v1\/setup\/([a-z_]+)\/$/);
      if (putStep && method === "PUT") {
        const body = JSON.parse(typeof init?.body === "string" ? init.body : "{}");
        const row = setup.find((s) => s.step_key === putStep[1]);
        if (row) {
          row.status = body.status;
          row.payload = body.payload ?? null;
          row.complete = body.status === "complete";
        }
        return ok(row ?? {});
      }
      if (url.split("?")[0].endsWith("/api/v1/setup/")) {
        // Fresh objects per GET, like a real API response: TanStack's
        // structural sharing skips the update when handed the same mutated
        // reference, and the wizard would never re-render.
        return ok(setup.map((s) => ({ ...s })));
      }

      const path = url.split("?")[0];
      const page = Number(new URLSearchParams(url.split("?")[1] ?? "").get("page") ?? "1");
      for (const [name, rows] of Object.entries(lists)) {
        if (!path.endsWith(`/api/v1/${name}/`)) continue;
        if (method === "POST") {
          if (failingPosts.includes(name)) {
            return jsonResponse(500, { detail: "could not save the row" });
          }
          const body = JSON.parse(typeof init?.body === "string" ? init.body : "{}");
          const row = { id: `new-${rows.length + 1}`, ...body };
          rows.push(row);
          return created(row);
        }
        const start = (page - 1) * PAGE_SIZE;
        const pageRows = rows.slice(start, start + PAGE_SIZE);
        return ok({
          count: rows.length,
          next:
            start + PAGE_SIZE < rows.length
              ? `http://localhost${path}?page=${page + 1}`
              : null,
          previous: null,
          results: pageRows.map((r) => ({ ...r })),
        });
      }
      return ok({ count: 0, next: null, previous: null, results: [] });
    }),
  );
  return calls;
}

const findCall = (calls: RecordedCall[], url: string, method: string) =>
  calls.find((c) => c.url.endsWith(url) && c.method === method);

/**
 * vi.waitUntil (not vi.waitFor): a call record is truthy only once the
 * request has actually been issued, and the assertion must not run against
 * an absent call.
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

function renderWizard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SetupWizard />
    </QueryClientProvider>,
  );
}

/** Steps 1..n complete so the wizard opens on step n+1 (first incomplete). */
const completedThrough = (n: number): StepOverrides =>
  Object.fromEntries(
    SETUP_KEYS.slice(0, n).map((key) => [key, { status: "complete", payload: {} }]),
  );

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("SetupWizard", () => {
  it("renders all ten steps with completion state and the progress percentage", async () => {
    stubWizardFetch(setupBody(completedThrough(2)), {});

    renderWizard();

    expect(await screen.findByRole("heading", { level: 1, name: /facility setup/i }));
    expect(screen.getAllByRole("listitem")).toHaveLength(10);
    expect(screen.getByText("20% complete")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");
    // Status is a label, never colour alone (design.md §23).
    expect(screen.getAllByText("Incomplete")).toHaveLength(8);
    expect(screen.getAllByText("Complete")).toHaveLength(2);
    const done = screen.getByRole("button", { name: /^1\. Hospital/ });
    expect(within(done).getByText("Complete")).toBeInTheDocument();
    const pending = screen.getByRole("button", { name: /^3\. Address/ });
    expect(within(pending).getByText("Incomplete")).toBeInTheDocument();
  });

  it("opens on the first incomplete step when the wizard is resumed", async () => {
    stubWizardFetch(setupBody(completedThrough(1)), {});

    renderWizard();

    expect(
      await screen.findByRole("heading", { level: 2, name: "Ownership level" }),
    ).toBeInTheDocument();
  });

  it("restores saved values into the form on resume", async () => {
    stubWizardFetch(
      setupBody({
        hospital_identity: {
          status: "in_progress",
          payload: { name: "Seed District Hospital" },
        },
      }),
      {},
    );

    renderWizard();

    expect(await screen.findByLabelText(/hospital name/i)).toHaveValue("Seed District Hospital");
  });

  it("saves the current step with Ctrl+S as in-progress without advancing", async () => {
    const calls = stubWizardFetch(setupBody(), {});

    renderWizard();
    await screen.findByRole("heading", { level: 2, name: "Hospital identity" });

    await userEvent.type(await screen.findByLabelText(/hospital name/i), "Seed District Hospital");
    // The keydown triggers an async save; the act wrapper lets the mutation
    // pipeline's state updates land inside the test's act scope.
    await act(async () => {
      fireEvent.keyDown(window, { key: "s", ctrlKey: true });
    });

    const put = await awaitCall(calls, "/api/v1/setup/hospital_identity/", "PUT");
    expect(JSON.parse(put.body ?? "{}")).toEqual({
      status: "in_progress",
      payload: { name: "Seed District Hospital" },
    });
    // Still on step 1: Ctrl+S saves, it does not advance.
    expect(screen.getByRole("heading", { level: 2, name: "Hospital identity" })).toBeInTheDocument();
    expect(await screen.findByText("Step saved.")).toBeInTheDocument();
  });

  it("validates before advancing, then PUTs the step complete and moves on", async () => {
    const calls = stubWizardFetch(setupBody(), {});

    renderWizard();
    await screen.findByRole("heading", { level: 2, name: "Hospital identity" });

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText(/hospital name is required/i)).toBeInTheDocument();
    expect(findCall(calls, "/api/v1/setup/hospital_identity/", "PUT")).toBeUndefined();

    await userEvent.type(screen.getByLabelText(/hospital name/i), "Seed District Hospital");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));

    const put = await awaitCall(calls, "/api/v1/setup/hospital_identity/", "PUT");
    expect(JSON.parse(put.body ?? "{}")).toEqual({
      status: "complete",
      payload: { name: "Seed District Hospital" },
    });
    const nextHeading = await screen.findByRole("heading", {
      level: 2,
      name: "Ownership level",
    });
    // The submitted form just unmounted; focus must land on the new step's
    // heading instead of falling to <body> (UI-002's focus clause).
    await waitFor(() => expect(nextHeading).toHaveFocus());
    // The invalidation refetched the spine: step 1 now shows its flag.
    const done = await screen.findByRole("button", { name: /^1\. Hospital/ });
    expect(within(done).getByText("Complete")).toBeInTheDocument();
  });

  it("submits and advances with Enter from inside the step form", async () => {
    const calls = stubWizardFetch(setupBody(), {});

    renderWizard();
    const name = await screen.findByLabelText(/hospital name/i);
    await userEvent.type(name, "Seed District Hospital");
    // jsdom does not implement Enter's implicit form submission, so the
    // submit event is dispatched directly — in a browser, Enter in the
    // input fires this same submit path.
    const form = name.closest("form");
    if (form === null) throw new Error("step form not found");
    await act(async () => {
      fireEvent.submit(form);
    });

    const put = await awaitCall(calls, "/api/v1/setup/hospital_identity/", "PUT");
    expect(JSON.parse(put.body ?? "{}")).toEqual({
      status: "complete",
      payload: { name: "Seed District Hospital" },
    });
    expect(
      await screen.findByRole("heading", { level: 2, name: "Ownership level" }),
    ).toBeInTheDocument();
  });

  it("surfaces a permission-denied PUT as an explicit alert naming the claim", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/v1/setup/")) return ok(setupBody());
        if (url.match(/\/api\/v1\/setup\/[a-z_]+\/$/) && init?.method === "PUT") {
          return jsonResponse(403, { detail: "missing identity.setup.manage" });
        }
        return ok({});
      }),
    );

    renderWizard();
    await screen.findByRole("heading", { level: 2, name: "Hospital identity" });
    await userEvent.type(screen.getByLabelText(/hospital name/i), "Seed District Hospital");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/identity\.setup\.manage/);
    expect(alert).toHaveTextContent(/not saved/i);
    // No silent no-op: the wizard stays on the refused step.
    expect(
      screen.getByRole("heading", { level: 2, name: "Hospital identity" }),
    ).toBeInTheDocument();
  });

  it("renders a server field error under its input and stays on the step", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/v1/setup/")) return ok(setupBody());
        if (url.match(/\/api\/v1\/setup\/[a-z_]+\/$/) && init?.method === "PUT") {
          return jsonResponse(400, { name: ["Hospital name is already taken."] });
        }
        return ok({});
      }),
    );

    renderWizard();
    await screen.findByRole("heading", { level: 2, name: "Hospital identity" });
    await userEvent.type(screen.getByLabelText(/hospital name/i), "Duplicate");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Hospital name is already taken.")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Hospital identity" }),
    ).toBeInTheDocument();
  });

  it("asks before discarding unsaved changes on Back, and keeps them when refused", async () => {
    stubWizardFetch(setupBody(completedThrough(1)), {});

    renderWizard();
    await screen.findByRole("heading", { level: 2, name: "Ownership level" });
    await userEvent.selectOptions(
      screen.getByLabelText(/facility level/i),
      "District Hospital",
    );

    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(confirm).toHaveBeenCalledWith(
      expect.stringMatching(/discard unsaved changes/i),
    );
    expect(
      screen.getByRole("heading", { level: 2, name: "Ownership level" }),
    ).toBeInTheDocument();

    confirm.mockReturnValue(true);
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(
      await screen.findByRole("heading", { level: 2, name: "Hospital identity" }),
    ).toBeInTheDocument();
  });

  it("lists existing departments and creates one through the shared table", async () => {
    const calls = stubWizardFetch(setupBody(completedThrough(5)), {
      facilities: [FACILITY],
      departments: [DEPARTMENT_OPD, DEPARTMENT_IPD],
      wards: [WARD],
      beds: [],
    });

    renderWizard();
    expect(
      await screen.findByRole("heading", { level: 2, name: "Departments, wards & beds" }),
    ).toBeInTheDocument();

    const departments = screen.getByRole("region", { name: "Departments" });
    expect(await within(departments).findByRole("cell", { name: "OPD" })).toBeInTheDocument();
    expect(within(departments).getByRole("cell", { name: "IPD" })).toBeInTheDocument();

    await userEvent.selectOptions(within(departments).getByLabelText(/facility/i), FACILITY_ID);
    await userEvent.type(within(departments).getByLabelText(/department name/i), "Paediatrics");
    await userEvent.click(within(departments).getByRole("button", { name: "Add department" }));

    const post = await awaitCall(calls, "/api/v1/departments/", "POST");
    const body = JSON.parse(post.body ?? "{}");
    expect(body).toMatchObject({
      facility: FACILITY_ID,
      name: "Paediatrics",
      opd_enabled: false,
      ipd_enabled: false,
    });
    expect(typeof body.effective_from).toBe("string");
    expect(
      await within(departments).findByRole("cell", { name: "Paediatrics" }),
    ).toBeInTheDocument();
  });

  it("surfaces a failed department add as an explicit alert, not a silent no-op", async () => {
    stubWizardFetch(
      setupBody(completedThrough(5)),
      { facilities: [FACILITY], departments: [], wards: [], beds: [] },
      ["departments"],
    );

    renderWizard();
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Departments, wards & beds",
      }),
    ).toBeInTheDocument();
    const departments = screen.getByRole("region", { name: "Departments" });
    await within(departments).findByRole("option", { name: FACILITY.name });
    await userEvent.selectOptions(
      within(departments).getByLabelText(/facility/i),
      FACILITY_ID,
    );
    await userEvent.type(within(departments).getByLabelText(/department name/i), "Cardiology");
    await userEvent.click(within(departments).getByRole("button", { name: "Add department" }));

    const alert = await within(departments).findByRole("alert");
    expect(alert).toHaveTextContent("could not save the row");
  });

  it("surfaces a failed ward add as an explicit alert, not a silent no-op", async () => {
    stubWizardFetch(
      setupBody(completedThrough(5)),
      { facilities: [FACILITY], departments: [DEPARTMENT_OPD], wards: [], beds: [] },
      ["wards"],
    );

    renderWizard();
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Departments, wards & beds",
      }),
    ).toBeInTheDocument();
    const wards = screen.getByRole("region", { name: "Wards" });
    // The ward form's department options come from the page-walking
    // fetch-all — waiting for one pins that the join source is loaded.
    await within(wards).findByRole("option", { name: DEPARTMENT_OPD.name });
    await userEvent.selectOptions(within(wards).getByLabelText(/department/i), DEPT_OPD_ID);
    await userEvent.type(within(wards).getByLabelText(/ward name/i), "ICU Ward");
    await userEvent.selectOptions(within(wards).getByLabelText(/ward type/i), "ICU");
    await userEvent.click(within(wards).getByRole("button", { name: "Add ward" }));

    const alert = await within(wards).findByRole("alert");
    expect(alert).toHaveTextContent("could not save the row");
  });

  it("surfaces a failed bed add as an explicit alert, not a silent no-op", async () => {
    stubWizardFetch(
      setupBody(completedThrough(5)),
      { facilities: [FACILITY], departments: [], wards: [WARD], beds: [] },
      ["beds"],
    );

    renderWizard();
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Departments, wards & beds",
      }),
    ).toBeInTheDocument();
    const beds = screen.getByRole("region", { name: "Beds" });
    await within(beds).findByRole("option", { name: WARD.name });
    await userEvent.selectOptions(within(beds).getByLabelText(/^ward/i), WARD_ID);
    await userEvent.type(within(beds).getByLabelText(/bed number/i), "B-9");
    await userEvent.click(within(beds).getByRole("button", { name: "Add bed" }));

    const alert = await within(beds).findByRole("alert");
    expect(alert).toHaveTextContent("could not save the row");
  });

  it("surfaces a failed service-unit add as an explicit alert, not a silent no-op", async () => {
    stubWizardFetch(
      setupBody(completedThrough(6)),
      { facilities: [FACILITY], "service-units": [] },
      ["service-units"],
    );

    renderWizard();
    expect(
      await screen.findByRole("heading", { level: 2, name: "Service units" }),
    ).toBeInTheDocument();
    const units = screen.getByRole("region", { name: "Service units" });
    await within(units).findByRole("option", { name: FACILITY.name });
    await userEvent.selectOptions(within(units).getByLabelText(/facility/i), FACILITY_ID);
    await userEvent.type(within(units).getByLabelText(/service unit name/i), "Central Lab");
    await userEvent.selectOptions(within(units).getByLabelText(/unit type/i), "Laboratory");
    await userEvent.click(within(units).getByRole("button", { name: "Add service unit" }));

    const alert = await within(units).findByRole("alert");
    expect(alert).toHaveTextContent("could not save the row");
  });

  it("surfaces a failed staff-position add as an explicit alert, not a silent no-op", async () => {
    stubWizardFetch(
      setupBody(completedThrough(7)),
      { departments: [DEPARTMENT_OPD], "staff-positions": [] },
      ["staff-positions"],
    );

    renderWizard();
    expect(
      await screen.findByRole("heading", { level: 2, name: "Staff positions" }),
    ).toBeInTheDocument();
    const positions = screen.getByRole("region", { name: "Staff positions" });
    await within(positions).findByRole("option", { name: DEPARTMENT_OPD.name });
    await userEvent.selectOptions(within(positions).getByLabelText(/department/i), DEPT_OPD_ID);
    await userEvent.type(within(positions).getByLabelText(/designation/i), "Staff Nurse");
    await userEvent.click(within(positions).getByRole("button", { name: "Add position" }));

    const alert = await within(positions).findByRole("alert");
    expect(alert).toHaveTextContent("could not save the row");
  });

  it("caps the tables at the backend's page size with a visible caption, and still names past-page-1 parents", async () => {
    stubWizardFetch(setupBody(completedThrough(5)), {
      facilities: [FACILITY],
      departments: [DEPARTMENT_OPD],
      wards: MANY_WARDS,
      beds: MANY_BEDS,
    });

    renderWizard();
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Departments, wards & beds",
      }),
    ).toBeInTheDocument();

    // Page 1 of a 103-row list is 50 rows — the truncation must be visible,
    // not a silent lie that looks like the whole list.
    const beds = screen.getByRole("region", { name: "Beds" });
    await within(beds).findByText("Showing 50 of 103");
    const wards = screen.getByRole("region", { name: "Wards" });
    await within(wards).findByText("Showing 50 of 51");
    const departments = screen.getByRole("region", { name: "Departments" });
    await within(departments).findByRole("cell", { name: "OPD" });
    expect(within(departments).queryByText(/^Showing \d+ of/)).not.toBeInTheDocument();

    // The beds reference ward-51, which sits on wards page 2: the join
    // resolves its name instead of degrading to the raw id.
    expect(await within(beds).findAllByRole("cell", { name: "Ward 51" })).toHaveLength(50);
    // The ward rows resolve their department through the same walker.
    expect(await within(wards).findAllByRole("cell", { name: "OPD" })).toHaveLength(50);
  });

  it("blocks a duplicate department name client-side before posting", async () => {
    const calls = stubWizardFetch(setupBody(completedThrough(5)), {
      facilities: [FACILITY],
      departments: [DEPARTMENT_OPD],
      wards: [],
      beds: [],
    });

    renderWizard();
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Departments, wards & beds",
      }),
    ).toBeInTheDocument();
    const departments = screen.getByRole("region", { name: "Departments" });
    // The pre-check reads the fetch-all list; its presence in the ward
    // form's select is what proves that source has loaded.
    const wards = screen.getByRole("region", { name: "Wards" });
    await within(departments).findByRole("option", { name: FACILITY.name });
    await within(wards).findByRole("option", { name: DEPARTMENT_OPD.name });
    await userEvent.selectOptions(
      within(departments).getByLabelText(/facility/i),
      FACILITY_ID,
    );
    // "opd" differs from the seeded "OPD" only in case — the pre-check is
    // case-insensitive, which is what makes it catch real duplicates.
    await userEvent.type(within(departments).getByLabelText(/department name/i), "opd");
    await userEvent.click(within(departments).getByRole("button", { name: "Add department" }));

    expect(await within(departments).findByText(/already exists/i)).toBeInTheDocument();
    expect(findCall(calls, "/api/v1/departments/", "POST")).toBeUndefined();
  });

  it("blocks a duplicate bed code within a ward client-side before posting", async () => {
    const calls = stubWizardFetch(setupBody(completedThrough(5)), {
      facilities: [FACILITY],
      departments: [DEPARTMENT_OPD],
      wards: [WARD],
      beds: [{ id: "bed-1", ward: WARD_ID, bed_number: "B-1", functional: true, active: true }],
    });

    renderWizard();
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Departments, wards & beds",
      }),
    ).toBeInTheDocument();
    const beds = screen.getByRole("region", { name: "Beds" });
    // The pre-check reads the loaded beds page; the seeded row's cell is
    // what proves that list has loaded.
    await within(beds).findByRole("cell", { name: "B-1" });
    await within(beds).findByRole("option", { name: WARD.name });
    await userEvent.selectOptions(within(beds).getByLabelText(/^ward/i), WARD_ID);
    await userEvent.type(within(beds).getByLabelText(/bed number/i), "B-1");
    await userEvent.click(within(beds).getByRole("button", { name: "Add bed" }));

    expect(await within(beds).findByText(/already exists/i)).toBeInTheDocument();
    expect(findCall(calls, "/api/v1/beds/", "POST")).toBeUndefined();
  });

  it("labels an MFA-gate 403 as the server's MFA instruction, not a missing claim", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.split("?")[0].endsWith("/api/v1/setup/")) return ok(setupBody());
        if (url.match(/\/api\/v1\/setup\/[a-z_]+\/$/) && init?.method === "PUT") {
          return jsonResponse(403, {
            detail:
              "Your role requires multi-factor authentication. Enrol a TOTP " +
              "device at /api/v1/mfa-devices/ and confirm it.",
            code: "mfa_required",
          });
        }
        return ok({});
      }),
    );

    renderWizard();
    await screen.findByRole("heading", { level: 2, name: "Hospital identity" });
    await userEvent.type(screen.getByLabelText(/hospital name/i), "Seed District Hospital");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/multi-factor authentication/i);
    expect(alert).not.toHaveTextContent(/identity\.setup\.manage/);
  });

  it("Next on a table step confirms before discarding a half-typed add-form", async () => {
    const calls = stubWizardFetch(setupBody(completedThrough(5)), {
      facilities: [FACILITY],
      departments: [],
      wards: [],
      beds: [],
    });

    renderWizard();
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Departments, wards & beds",
      }),
    ).toBeInTheDocument();
    const departments = screen.getByRole("region", { name: "Departments" });
    await userEvent.type(within(departments).getByLabelText(/department name/i), "Half");

    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(confirm).toHaveBeenCalledWith(
      expect.stringMatching(/discard unsaved changes/i),
    );
    // Refused: nothing is PUT and the half-typed form is still in place.
    expect(findCall(calls, "/api/v1/setup/departments_wards_beds/", "PUT")).toBeUndefined();
    expect(
      screen.getByRole("heading", { level: 2, name: "Departments, wards & beds" }),
    ).toBeInTheDocument();
    expect(within(departments).getByLabelText(/department name/i)).toHaveValue("Half");
  });

  it("posts a reference-data row with the value shape the step's kind requires", async () => {
    const calls = stubWizardFetch(setupBody(completedThrough(8)), { "reference-data": [] });

    renderWizard();
    expect(
      await screen.findByRole("heading", { level: 2, name: "Reference data" }),
    ).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText(/kind/i), "catchment_population");
    await userEvent.type(screen.getByLabelText(/key/i), "deoni");
    await userEvent.type(screen.getByLabelText(/value/i), "125000");
    await userEvent.click(screen.getByRole("button", { name: "Add reference row" }));

    const post = await awaitCall(calls, "/api/v1/reference-data/", "POST");
    expect(JSON.parse(post.body ?? "{}")).toEqual({
      kind: "catchment_population",
      key: "deoni",
      value: { population: 125000 },
    });
    expect(await screen.findByRole("cell", { name: "deoni" })).toBeInTheDocument();
  });

  it("mirrors the server's non-negative baseline rule client-side before posting", async () => {
    const calls = stubWizardFetch(setupBody(completedThrough(9)), { "baseline-inputs": [] });

    renderWizard();
    expect(
      await screen.findByRole("heading", { level: 2, name: "Indicator baseline inputs" }),
    ).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/indicator source code/i), "HMI-10");
    await userEvent.type(screen.getByLabelText(/period/i), "2026-10");
    fireEvent.change(screen.getByLabelText(/^value/i), { target: { value: "-1" } });
    await userEvent.click(screen.getByRole("button", { name: "Add baseline input" }));

    expect(await screen.findByText(/cannot be negative/i)).toBeInTheDocument();
    expect(findCall(calls, "/api/v1/baseline-inputs/", "POST")).toBeUndefined();

    fireEvent.change(screen.getByLabelText(/^value/i), { target: { value: "85.5" } });
    await userEvent.click(screen.getByRole("button", { name: "Add baseline input" }));

    const post = await awaitCall(calls, "/api/v1/baseline-inputs/", "POST");
    expect(JSON.parse(post.body ?? "{}")).toEqual({
      indicator_source_code: "HMI-10",
      period: "2026-10",
      value: 85.5,
    });
  });

  it("finishing the last step PUTs a counts summary as its payload", async () => {
    const calls = stubWizardFetch(setupBody(completedThrough(9)), { "baseline-inputs": [] });

    renderWizard();
    await screen.findByRole("heading", { level: 2, name: "Indicator baseline inputs" });
    expect(screen.getByRole("button", { name: "Finish" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Finish" }));

    const put = await awaitCall(calls, "/api/v1/setup/indicators_baseline/", "PUT");
    expect(JSON.parse(put.body ?? "{}")).toEqual({
      status: "complete",
      payload: { baseline_inputs: 0 },
    });
    expect(await screen.findByText("100% complete")).toBeInTheDocument();
  });

  it("shows a load failure honestly instead of an empty wizard", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(500, { detail: "boom" })),
    );

    renderWizard();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not load the setup state/i);
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
  });

  it("keeps the /admin/setup nav item enabled (route contract)", () => {
    const item = NAV_ITEMS.find((i) => i.path === "/admin/setup");
    expect(item).toBeDefined();
    expect(item?.availability).toBe("enabled");
  });
});


