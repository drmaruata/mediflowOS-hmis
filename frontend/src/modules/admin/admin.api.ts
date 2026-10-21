/**
 * Admin API — users, roles, the configuration edit surface and the audit
 * trail (TEN-004, TEN-007, TEN-008, AUD-003; SET-002/003/010/011 for the
 * configuration rows). Types live beside their fetch functions (AGENTS.md §5).
 *
 * The backend is the authority for every rule mirrored here: deactivation is
 * the only user offboarding path (UserViewSet routes no DELETE), the
 * permission codes below are the exact strings RequirePermission matches, and
 * the break-glass reason travels in the X-Break-Glass-Reason header the
 * server reads (auth_views.py:28) — an empty body reason grants nothing.
 */

import { apiClient } from "@/lib/apiClient";
import { extractServerErrors } from "@/lib/serverErrors";

export interface Page<T> {
  readonly count: number;
  readonly next: string | null;
  readonly previous: string | null;
  readonly results: T[];
}

/**
 * The backend-enforced permission vocabulary: every code the server's
 * RequirePermission / WritePermissionMixin gates are grep'd from
 * backend/apps/identity_tenancy (views.py:72, :414, :427, :447, :547, :604,
 * :719, :811). The matrix presents these as the recommended toggles; the
 * `permissions` claim is a free-text list server-side, so a role may also
 * carry custom codes the UI keeps visible and editable.
 *
 * `platform.*` codes are refused on tenant roles by
 * RoleSerializer.validate_permissions, so the matrix renders them disabled
 * rather than offering a toggle that can only ever 400.
 */
export const BACKEND_PERMISSION_CODES = [
  "identity.roles.write",
  "identity.memberships.write",
  "identity.users.manage",
  "identity.setup.manage",
  "identity.reference_data.write",
  "identity.baseline_input.write",
  "identity.break_glass.revoke",
  "platform.tenants.manage",
] as const;

export const isPlatformCode = (code: string): boolean => code.startsWith("platform.");

/**
 * The alert text for a form-level failure: the server's detail when present,
 * otherwise any field errors the form had no matching field for — a
 * body-shaped 400 must not be silently dropped — else null so the caller
 * supplies its own fallback. Same "no server message dropped" rule the
 * patient registration screen set (Task 33).
 */
export function formAlertText(error: unknown): string | null {
  const { general, fieldErrors } = extractServerErrors(error);
  if (general !== null) return general;
  const joined = Object.values(fieldErrors).join(" ");
  return joined !== "" ? joined : null;
}

// --- users (TEN-008) ---------------------------------------------------------

export interface AdminUser {
  readonly id: string;
  readonly username: string;
  readonly email: string;
  readonly date_joined: string;
  readonly role_id: string | null;
  readonly facility_id: string | null;
  readonly active: boolean | null;
}

export interface CreateUserInput {
  readonly username: string;
  readonly password: string;
  readonly email: string;
  readonly role_id: string;
}

export const fetchUsersPage = (page: number): Promise<Page<AdminUser>> =>
  apiClient<Page<AdminUser>>(`/api/v1/users/?page=${page}`);

export function createUser(input: CreateUserInput): Promise<AdminUser> {
  return apiClient<AdminUser>("/api/v1/users/", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

/** Offboarding flips the membership off; the account survives for audit history. */
export function deactivateUser(id: string): Promise<AdminUser> {
  return apiClient<AdminUser>(`/api/v1/users/${id}/deactivate/`, { method: "POST" });
}

// --- roles (TEN-004) ----------------------------------------------------------

export interface Role {
  readonly id: string;
  readonly name: string;
  readonly permissions: string[];
  readonly require_mfa: boolean;
  readonly allows_break_glass: boolean;
  readonly created_at: string;
}

export interface RolePatch {
  readonly permissions: string[];
  readonly require_mfa: boolean;
  readonly allows_break_glass: boolean;
}

export function updateRole(id: string, patch: RolePatch): Promise<Role> {
  return apiClient<Role>(`/api/v1/roles/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

// --- configuration rows (SET-002/003, edit surface for the wizard's CRUD) ----

export interface DepartmentRow {
  readonly id: string;
  readonly facility: string;
  readonly name: string;
  readonly opd_enabled: boolean;
  readonly ipd_enabled: boolean;
  readonly active: boolean;
  readonly effective_from: string;
  readonly effective_to: string | null;
}

export interface WardRow {
  readonly id: string;
  readonly department: string;
  readonly name: string;
  readonly type_tag: string;
  readonly active: boolean;
}

export interface BedRow {
  readonly id: string;
  readonly ward: string;
  readonly bed_number: string;
  readonly functional: boolean;
  readonly occupied: boolean;
  readonly active: boolean;
}

export interface DepartmentPatch {
  readonly name: string;
  readonly opd_enabled: boolean;
  readonly ipd_enabled: boolean;
  readonly active: boolean;
}

export interface WardPatch {
  readonly department: string;
  readonly name: string;
  readonly type_tag: string;
  readonly active: boolean;
}

export interface BedPatch {
  readonly bed_number: string;
  readonly functional: boolean;
  readonly active: boolean;
}

export function updateDepartment(id: string, patch: DepartmentPatch): Promise<DepartmentRow> {
  return apiClient<DepartmentRow>(`/api/v1/departments/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function updateWard(id: string, patch: WardPatch): Promise<WardRow> {
  return apiClient<WardRow>(`/api/v1/wards/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

// Occupied never travels: it is live admission state, not configuration
// (design.md §7 — occupancy cannot be silently cleared), and BedPatch
// carries no key for it by construction.
export function updateBed(id: string, patch: BedPatch): Promise<BedRow> {
  return apiClient<BedRow>(`/api/v1/beds/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export const fetchBedsPage = (page: number): Promise<Page<BedRow>> =>
  apiClient<Page<BedRow>>(`/api/v1/beds/?page=${page}`);

// --- audit trail (AUD-003) ----------------------------------------------------

export interface AuditEvent {
  readonly id: string;
  readonly tenant_id: string;
  readonly user_id: string | null;
  readonly action: string;
  readonly entity_type: string;
  readonly entity_id: string;
  readonly reason: string | null;
  readonly source: string | null;
  readonly source_ip: string | null;
  readonly occurred_at: string;
}

export interface AuditFilters {
  readonly entityType: string;
  readonly entityId: string;
  readonly page: number;
}

/**
 * `entity_id` is only meaningful alongside `entity_type` server-side
 * (audit/views.py applies it inside the type branch), so the client never
 * sends one without the other — a lone id would look applied while the
 * response still carried every row of every entity.
 */
export function fetchAuditPage(filters: AuditFilters): Promise<Page<AuditEvent>> {
  const params = new URLSearchParams({ page: String(filters.page) });
  if (filters.entityType !== "") {
    params.set("entity_type", filters.entityType);
    if (filters.entityId !== "") params.set("entity_id", filters.entityId);
  }
  return apiClient<Page<AuditEvent>>(`/api/v1/audit-log/?${params.toString()}`);
}

// --- break-glass (TEN-007) -----------------------------------------------------

export interface BreakGlassGrant {
  readonly access_id: string;
  readonly granted_at: string;
}

export function requestBreakGlass(input: {
  resourceType: string;
  resourceId: string;
  reason: string;
}): Promise<BreakGlassGrant> {
  return apiClient<BreakGlassGrant>("/api/v1/auth/break-glass/", {
    method: "POST",
    headers: { "X-Break-Glass-Reason": input.reason },
    body: JSON.stringify({
      resource_type: input.resourceType,
      resource_id: input.resourceId,
    }),
  });
}

// --- page-walking fetch-alls --------------------------------------------------
//
// Roles, departments and wards are realistically small but the backend pages
// at a fixed 50 rows, so the screens that need the whole set (the role
// catalogue, the parent-name joins) walk `next` until null — the same
// approach modules/setup/setup.api.ts and patient.api.ts take.

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

export const fetchRoles = (): Promise<Role[]> => fetchAllPages<Role>("/api/v1/roles/");

export const fetchAllDepartments = (): Promise<DepartmentRow[]> =>
  fetchAllPages<DepartmentRow>("/api/v1/departments/");

export const fetchAllWards = (): Promise<WardRow[]> =>
  fetchAllPages<WardRow>("/api/v1/wards/");
