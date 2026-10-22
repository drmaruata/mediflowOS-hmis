/**
 * Patient registry API — search, registration, duplicate check and the
 * verification queue (REG-001..007, P-REG-2/4/6). Types live beside their
 * fetch functions (AGENTS.md §5).
 *
 * The UHID is server-minted (REG-001): the payload builder never carries a
 * `uhid` key and no screen offers a UHID input — the identifier only ever
 * travels server→client.
 *
 * REG-008 honesty: mobile and ABHA are stored encrypted with keyed-HMAC
 * exact-match indexes, so the server matches only the *complete* number. A
 * fragment deliberately matches nothing; the screens state that degradation
 * instead of attempting client-side fuzzy matching.
 */

import { apiClient } from "@/lib/apiClient";

export type VerificationStatus = "pending" | "verified" | "ambiguous";

/** demographics is free-form JSON server-side; these are the keys the UI reads. */
export interface PatientDemographics {
  name?: string;
  gender?: string;
  dob?: string;
  yearOfBirth?: number | string;
  year_of_birth?: number | string;
  age_years?: number | string;
  [key: string]: unknown;
}

export interface Patient {
  readonly id: string;
  readonly tenant_id: string;
  readonly uhid: string;
  readonly abha_number: string | null;
  readonly abha_address: string | null;
  readonly verification_status: VerificationStatus;
  readonly verified_at: string | null;
  readonly demographics: PatientDemographics;
  readonly contact: { readonly mobile?: string } | null;
  readonly address: Record<string, unknown> | null;
  readonly scheme_category: Record<string, unknown> | null;
  readonly consent_flags: Record<string, unknown>;
  readonly intake_channel: string;
  readonly created_at: string;
}

/** The OPD token a registration mints (REG-010); absent without a department. */
export interface IntakeToken {
  readonly series: string;
  readonly number: number;
}

/** POST /patients/ answers the patient plus a response-level `token`.
 *  May include `visit_id` when an OPD encounter is created alongside registration.
 */
export type RegistrationResult = Patient & { readonly token?: IntakeToken; readonly visit_id?: string };

/** REG-003 returns the minimum a clerk needs to recognise a match — no full PHI. */
export interface DuplicateCandidate {
  readonly id: string;
  readonly uhid: string;
  readonly name: string | null;
  readonly gender: string | null;
  readonly year_of_birth: number | null;
  readonly mobile_masked: string;
}

export interface DuplicateCheckResult {
  readonly warn: boolean;
  readonly candidates: DuplicateCandidate[];
}

export interface DuplicateCheckInput {
  name?: string;
  dob?: string;
  mobile?: string;
  abha_number?: string;
}

/** DRF's PageNumberPagination envelope (mirrors modules/setup/setup.api.ts). */
interface Page<T> {
  readonly count: number;
  readonly next: string | null;
  readonly results: T[];
}

/** The intake picker needs only these two fields of a department row. */
export interface DepartmentOption {
  readonly id: string;
  readonly name: string;
}

/**
 * The patient table's audit entity name: audit rows name the record by its
 * db_table (patient_registry/models.py Meta, "registry.patient"), so the
 * profile's access-history link and the break-glass grant both use this —
 * audit/views.py filters on exactly this string.
 */
export const PATIENT_AUDIT_ENTITY_TYPE = "registry.patient";

// --- fetch functions -------------------------------------------------------

export async function searchPatients(term: string): Promise<Patient[]> {
  return apiClient<Patient[]>(
    `/api/v1/patients/search/?q=${encodeURIComponent(term.trim())}`,
  );
}

export async function fetchPatient(id: string): Promise<Patient> {
  return apiClient<Patient>(`/api/v1/patients/${id}/`);
}

export async function createPatient(
  payload: RegistrationPayload,
): Promise<RegistrationResult> {
  return apiClient<RegistrationResult>("/api/v1/patients/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** REG-003's pre-submit probe. Advisory — the server decides at create. */
export async function duplicateCheck(
  candidate: DuplicateCheckInput,
): Promise<DuplicateCheckResult> {
  return apiClient<DuplicateCheckResult>("/api/v1/patients/duplicate-check/", {
    method: "POST",
    body: JSON.stringify(candidate),
  });
}

/** P-REG-6: pending registrations and ambiguous ABDM multi-candidate rows (ABD-009). */
export async function fetchVerificationQueue(): Promise<Patient[]> {
  return apiClient<Patient[]>("/api/v1/patients/verification_queue/");
}

export async function verifyPatient(id: string): Promise<Patient> {
  return apiClient<Patient>(`/api/v1/patients/${id}/verify/`, { method: "POST" });
}

/**
 * OPD-enabled departments for the intake picker (REG-012). Walks every page
 * like the setup wizard's fetch-alls: an OPD department past the backend's
 * fixed 50-row page must still be selectable at the counter.
 */
export async function fetchOpdDepartments(): Promise<DepartmentOption[]> {
  const rows: DepartmentOption[] = [];
  let next: string | null = "/api/v1/departments/?opd_enabled=true";
  while (next !== null) {
    const page: Page<DepartmentOption> = await apiClient<
      Page<DepartmentOption>
    >(stripOrigin(next));
    rows.push(...page.results);
    next = page.next;
  }
  return rows;
}

/**
 * The counter's default view at /patients: every patient registered on one
 * calendar day, via the list action's `registered_on` filter. Pages are
 * walked — the backend's fixed 50-row page must not silently truncate a
 * busy outpatient day. The date parameter is the browser's local day;
 * the server re-cuts it against its own TIME_ZONE.
 */
export async function fetchPatientsRegisteredOn(
  dateISO: string,
): Promise<Patient[]> {
  const rows: Patient[] = [];
  let next: string | null = `/api/v1/patients/?registered_on=${dateISO}`;
  while (next !== null) {
    const page: Page<Patient> = await apiClient<Page<Patient>>(stripOrigin(next));
    rows.push(...page.results);
    next = page.next;
  }
  return rows;
}

/** DRF's `next` is absolute while apiClient takes a path — strip the origin. */
function stripOrigin(next: string): string {
  const { pathname, search } = new URL(next, window.location.origin);
  return pathname + search;
}

// --- pure helpers ----------------------------------------------------------

/** services.birth_year mirror: dob (ISO or bare year), yearOfBirth, then age_years. */
export function birthYearFromDemographics(
  demographics: PatientDemographics,
): number | null {
  for (const key of ["dob", "dateOfBirth", "date_of_birth"]) {
    const match = /(\d{4})/.exec(String(demographics[key] ?? ""));
    if (match) return Number(match[1]);
  }
  for (const key of ["yearOfBirth", "year_of_birth"]) {
    const value = demographics[key];
    if (value !== undefined && value !== null && value !== "") {
      const year = Number(value);
      if (Number.isFinite(year)) return year;
    }
  }
  const age = demographics.age_years;
  if (age !== undefined && age !== null && age !== "") {
    const years = Number(age);
    if (Number.isFinite(years)) return new Date().getFullYear() - years;
  }
  return null;
}

/**
 * validation.py mirror (MOBILE_RE + normalise_mobile): a formatted +91/0
 * prefix is accepted exactly as the server canonicalises it. Validation
 * only — the raw string is sent and the server canonicalises what is stored.
 */
export function isValidIndianMobile(value: string): boolean {
  let digits = value.replace(/\D/g, "");
  if (digits.startsWith("0")) digits = digits.slice(1);
  if (digits.startsWith("91") && digits.length === 12) digits = digits.slice(2);
  return /^[6-9]\d{9}$/.test(digits);
}

/**
 * Full years between a `yyyy-mm-dd` birth date and today — the counter's
 * auto-calculated age, rendered read-only. Null for an empty, unparseable
 * or future date: the form schema explains the problem, this helper stays
 * silent. Age is whole local-calendar years (a birthday reached today
 * counts).
 */
export function ageFromDob(dob: string): number | null {
  if (dob === "") return null;
  const born = new Date(`${dob}T00:00:00`);
  const now = new Date();
  if (Number.isNaN(born.valueOf()) || born.valueOf() > now.valueOf()) {
    return null;
  }
  let age = now.getFullYear() - born.getFullYear();
  if (
    now.getMonth() < born.getMonth() ||
    (now.getMonth() === born.getMonth() && now.getDate() < born.getDate())
  ) {
    age -= 1;
  }
  return age;
}

/**
 * The browser's local calendar day as YYYY-MM-DD — never `toISOString()`,
 * whose UTC day differs from the local one near midnight (a counter
 * registering in a night shift would fetch the wrong day). The server
 * applies the hospital's own TIME_ZONE, which is the day a clerk means.
 */
export function localDateISO(now: Date = new Date()): string {
  const pad = (value: number): string => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/**
 * Client-side tenant guard: the server scopes every query by the signed
 * token, but a row of another tenant must not render even if a broken or
 * misrouted response ever delivered one — refuse, never display (the
 * cross-tenant tests pin this against a mocked foreign row).
 */
export function sameTenant(
  row: { readonly tenant_id: string },
  tenantId: string | null,
): boolean {
  return tenantId !== null && row.tenant_id === tenantId;
}

/** Visible state text — never colour alone (design.md §23). */
export function verificationLabel(status: VerificationStatus): string {
  switch (status) {
    case "pending":
      return "Pending verification";
    case "verified":
      return "Verified";
    case "ambiguous":
      return "Ambiguous";
  }
}

// --- registration form → wire translation ----------------------------------

export interface RegistrationFormValues {
  readonly name: string;
  readonly gender: string;
  readonly dob: string;
  readonly address: string;
  readonly mobile: string;
  readonly abha_number: string;
  readonly intake_department_id: string;
}

export interface RegistrationPayload {
  readonly demographics: {
    readonly name: string;
    readonly gender: string;
    readonly dob: string;
  };
  /** The counter's single free-text address; `full` is its only key (REG-005). */
  readonly address: { readonly full: string };
  readonly contact?: { readonly mobile: string };
  readonly abha_number?: string;
  readonly intake_department_id: string;
  readonly intake_channel: "counter";
}

/**
 * Form values → the wire shape. REG-007: a full name, a gender and a birth
 * key are what the server demands — the counter's mandatory date of birth is
 * that key (the on-screen age is derived, never sent), and it mirrors what
 * the clerk entered (REG-003 matches on the same key). No `uhid` key can
 * appear here — REG-001 mints it server-side.
 */
export function buildRegistrationPayload(
  values: RegistrationFormValues,
): RegistrationPayload {
  return {
    demographics: { name: values.name, gender: values.gender, dob: values.dob },
    address: { full: values.address.trim() },
    // REG-005: this screen is the counter channel.
    intake_channel: "counter",
    intake_department_id: values.intake_department_id,
    ...(values.mobile.trim() !== ""
      ? { contact: { mobile: values.mobile.trim() } }
      : {}),
    ...(values.abha_number.trim() !== ""
      ? { abha_number: values.abha_number.trim() }
      : {}),
  };
}
