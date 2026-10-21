/**
 * Setup wizard API — the resumable state spine plus the CRUD resources the
 * wizard's table steps write through (SET-001, SET-006, SET-007, SET-008,
 * SET-009).
 *
 * GET /api/v1/setup/ is the orchestrated ten-step spine: every step always
 * appears with a status and a `complete` flag, so resumption restores the
 * whole wizard (the backend's tests/integration/test_setup_wizard.py pins
 * this). PUT /api/v1/setup/{step_key}/ upserts one step: `status` and
 * `payload` are both optional server-side, but the wizard always sends both —
 * saving a draft and finishing a step are distinct wizard events and the
 * row's fate must never be ambiguous. The step payload is free-form JSON by
 * design (SetupProgress's docstring); the shapes below are the wizard's
 * contract, mirrored by the Zod schemas in steps/*.tsx.
 *
 * Form steps keep their own values in the payload, so a resumed session
 * restores what was typed. Table steps keep their rows in the resources'
 * own tables and store only a counts summary, because the rows are the
 * restorable state and `complete` is an explicit status, never implied by a
 * non-empty payload.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { UseMutationResult } from "@tanstack/react-query";

import { apiClient } from "@/lib/apiClient";
import { ApiError } from "@/lib/apiClient";

export const SETUP_STEP_KEYS = [
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

export type SetupStepKey = (typeof SETUP_STEP_KEYS)[number];

export type SetupStatus = "pending" | "in_progress" | "complete";

export interface SetupStep {
  readonly step_key: SetupStepKey;
  readonly status: SetupStatus;
  readonly payload: Record<string, unknown> | null;
  readonly complete: boolean;
  readonly updated_at: string | null;
}

export interface SaveStepInput {
  stepKey: SetupStepKey;
  status: SetupStatus;
  payload: Record<string, unknown>;
}

export async function fetchSetupSteps(): Promise<SetupStep[]> {
  return apiClient<SetupStep[]>("/api/v1/setup/");
}

export async function saveSetupStep(input: SaveStepInput): Promise<SetupStep> {
  return apiClient<SetupStep>(`/api/v1/setup/${input.stepKey}/`, {
    method: "PUT",
    body: JSON.stringify({ status: input.status, payload: input.payload }),
  });
}

/**
 * The wizard's one step-state mutation. Invalidating ["setup"] refetches the
 * spine after every save, which is what flips the stepper's completion flags
 * and the percentage — the client never optimistically marks a step done.
 */
export function useSaveSetupStep(stepKey: SetupStepKey): UseMutationResult<
  SetupStep,
  unknown,
  { status: SetupStatus; payload: Record<string, unknown> }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: { status: SetupStatus; payload: Record<string, unknown> }) =>
      saveSetupStep({ stepKey, status: vars.status, payload: vars.payload }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["setup"] });
    },
  });
}

/** Narrow a free-form stored payload to a string field, or "" (SET-008). */
export function payloadString(
  payload: Record<string, unknown> | null,
  key: string,
): string {
  const value = payload?.[key];
  return typeof value === "string" ? value : "";
}

/** Narrow a stored payload to a list of string fields, or []. */
export function payloadStringList(
  payload: Record<string, unknown> | null,
  key: string,
): string[] {
  const value = payload?.[key];
  return Array.isArray(value) && value.every((v) => typeof v === "string") ? value : [];
}

/** Narrow a stored payload to a non-negative number field, or null. */
export function payloadNumber(
  payload: Record<string, unknown> | null,
  key: string,
): number | null {
  const value = payload?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

// ---------------------------------------------------------------------------
// CRUD resources the table steps consume. Lists are paginated by the backend
// (PageNumberPagination); `count` is the tenant-wide total, which the counts
// summaries use, and `results` is the current page the tables render.
// ---------------------------------------------------------------------------

export interface Page<T> {
  readonly count: number;
  readonly next: string | null;
  readonly previous: string | null;
  readonly results: T[];
}

export interface Facility {
  readonly id: string;
  readonly name: string;
  readonly level: string;
}

export interface Department {
  readonly id: string;
  readonly facility: string;
  readonly name: string;
  readonly opd_enabled: boolean;
  readonly ipd_enabled: boolean;
  readonly active: boolean;
  readonly effective_from: string;
  readonly effective_to: string | null;
}

export interface Ward {
  readonly id: string;
  readonly department: string;
  readonly name: string;
  readonly type_tag: string;
  readonly active: boolean;
}

export interface Bed {
  readonly id: string;
  readonly ward: string;
  readonly bed_number: string;
  readonly functional: boolean;
  readonly active: boolean;
}

export interface ServiceUnit {
  readonly id: string;
  readonly facility: string;
  readonly name: string;
  readonly type_tag: string;
}

export interface StaffPosition {
  readonly id: string;
  readonly department: string;
  readonly designation: string;
  readonly specialty: string | null;
  readonly sanctioned: number;
  readonly in_position: number;
}

export interface ReferenceDataRow {
  readonly id: string;
  readonly kind: string;
  readonly key: string;
  readonly value: Record<string, unknown>;
  readonly active: boolean;
}

export interface BaselineInputRow {
  readonly id: string;
  readonly indicator_source_code: string;
  readonly period: string;
  readonly value: number;
  readonly source: string;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  return apiClient<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export const fetchFacilities = (): Promise<Page<Facility>> =>
  apiClient<Page<Facility>>("/api/v1/facilities/");

export const fetchDepartments = (): Promise<Page<Department>> =>
  apiClient<Page<Department>>("/api/v1/departments/");

export const createDepartment = (body: {
  facility: string;
  name: string;
  effective_from: string;
  opd_enabled: boolean;
  ipd_enabled: boolean;
}): Promise<Department> => post<Department>("/api/v1/departments/", body);

export const fetchWards = (): Promise<Page<Ward>> =>
  apiClient<Page<Ward>>("/api/v1/wards/");

export const createWard = (body: {
  department: string;
  name: string;
  type_tag: string;
}): Promise<Ward> => post<Ward>("/api/v1/wards/", body);

export const fetchBeds = (): Promise<Page<Bed>> =>
  apiClient<Page<Bed>>("/api/v1/beds/");

export const createBed = (body: { ward: string; bed_number: string }): Promise<Bed> =>
  post<Bed>("/api/v1/beds/", body);

export const fetchServiceUnits = (): Promise<Page<ServiceUnit>> =>
  apiClient<Page<ServiceUnit>>("/api/v1/service-units/");

export const createServiceUnit = (body: {
  facility: string;
  name: string;
  type_tag: string;
}): Promise<ServiceUnit> => post<ServiceUnit>("/api/v1/service-units/", body);

export const fetchStaffPositions = (): Promise<Page<StaffPosition>> =>
  apiClient<Page<StaffPosition>>("/api/v1/staff-positions/");

export const createStaffPosition = (body: {
  department: string;
  designation: string;
  specialty: string;
  sanctioned: number;
  in_position: number;
}): Promise<StaffPosition> => post<StaffPosition>("/api/v1/staff-positions/", body);

export const fetchReferenceData = (): Promise<Page<ReferenceDataRow>> =>
  apiClient<Page<ReferenceDataRow>>("/api/v1/reference-data/");

export const createReferenceData = (body: {
  kind: string;
  key: string;
  value: Record<string, unknown>;
}): Promise<ReferenceDataRow> => post<ReferenceDataRow>("/api/v1/reference-data/", body);

export const fetchBaselineInputs = (): Promise<Page<BaselineInputRow>> =>
  apiClient<Page<BaselineInputRow>>("/api/v1/baseline-inputs/");

export const createBaselineInput = (body: {
  indicator_source_code: string;
  period: string;
  value: number;
}): Promise<BaselineInputRow> =>
  post<BaselineInputRow>("/api/v1/baseline-inputs/", body);

// ---------------------------------------------------------------------------
// Page-walking fetch-all. Every list is paginated at the backend's fixed
// PAGE_SIZE 50 with no client page-size control, so a join source read one
// page would degrade parent names to raw UUIDs once the parent sits past
// page 1. Only the realistically small join sources (departments, wards)
// walk `next` until null; the main tables stay single-page behind a visible
// truncation caption (full pagination belongs to the admin table screens).
// ---------------------------------------------------------------------------

/**
 * DRF's `next` is an absolute URL while apiClient takes a path — strip the
 * origin so walked pages keep the auth header and the refresh logic.
 * shortcut: a VITE_API_BASE that itself carries a path prefix would be
 * doubled here; no such deployment exists today.
 */
function nextPagePath(next: string): string {
  const { pathname, search } = new URL(next, window.location.origin);
  return pathname + search;
}

async function fetchAllPages<T>(path: string): Promise<T[]> {
  const rows: T[] = [];
  let next: string | null = path;
  while (next !== null) {
    const page: Page<T> = await apiClient<Page<T>>(nextPagePath(next));
    rows.push(...page.results);
    next = page.next;
  }
  return rows;
}

export const fetchAllDepartments = (): Promise<Department[]> =>
  fetchAllPages<Department>("/api/v1/departments/");

export const fetchAllWards = (): Promise<Ward[]> => fetchAllPages<Ward>("/api/v1/wards/");

// ---------------------------------------------------------------------------
// Server errors. The server stays the authority: DRF 400 bodies are field
// maps ({name: ["..."]}) or a detail string; the client maps them back onto
// the forms field-by-field instead of showing one generic failure.
// ---------------------------------------------------------------------------

export interface ServerErrorShape {
  fieldErrors: Record<string, string>;
  general: string | null;
}

export function extractServerErrors(error: unknown): ServerErrorShape {
  const fallback =
    error instanceof Error ? error.message : "Something went wrong. Try again.";
  if (!(error instanceof ApiError)) return { fieldErrors: {}, general: fallback };

  let body: unknown = null;
  try {
    body = JSON.parse(error.message);
  } catch {
    // Not a JSON body (a plain-text refusal): surface it verbatim.
  }

  const fieldErrors: Record<string, string> = {};
  let general: string | null = null;
  if (body !== null && typeof body === "object" && !Array.isArray(body)) {
    for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
      const message = Array.isArray(value)
        ? value.every((v) => typeof v === "string")
          ? value.join(" ")
          : null
        : typeof value === "string"
          ? value
          : null;
      if (message === null) continue;
      if (key === "detail" || key === "non_field_errors") general = message;
      else fieldErrors[key] = message;
    }
  }
  // A field map carries the failure in the form's own errors — a general
  // alert would just echo raw JSON back at the user.
  if (general === null && Object.keys(fieldErrors).length > 0) {
    return { fieldErrors, general: null };
  }
  return { fieldErrors, general: general ?? fallback };
}
