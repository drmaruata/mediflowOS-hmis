/**
 * kiosk.api — fetch layer for the public counter token display (UI-003,
 * UI_UX_design §7 "Counter token display (kiosk)").
 *
 * Deliberately not @/lib/apiClient: that wrapper reads its bearer from the
 * interactive `mediflow-auth` store and answers a 401 with the refresh
 * flow, which redirects a dead session to sign-in. A kiosk owns a
 * facility-scoped read-only token with no refresh, must never inherit a
 * clerk's session, and must never show login UI (§824) — so this minimal
 * fetch reads its own storage key and surfaces the raw 401 instead.
 *
 * R1 provisioning is out-of-band (no admin tooling in this task): an
 * administrator creates a read-only `kiosk` role on the Roles screen (the
 * backend has no seeded kiosk role), obtains a token for a kiosk service
 * user via POST /auth/token, and installs the raw JWT in localStorage on
 * the display. localStorage — not the interactive app's sessionStorage —
 * so the provisioned display survives browser restarts without
 * re-provisioning. The fetcher re-reads storage on every poll, so a
 * replaced token takes effect on the next poll without a reload.
 */

export const KIOSK_TOKEN_STORAGE_KEY = "mediflow-kiosk";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export class KioskApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "KioskApiError";
  }
}

export function getKioskToken(): string | null {
  return window.localStorage.getItem(KIOSK_TOKEN_STORAGE_KEY);
}

/**
 * The queue endpoint serialises whole Token rows, but a public display only
 * types what it renders — patient_id and tenant_id are deliberately absent
 * so a patient identifier can never reach the screen (§825).
 */
export interface QueueToken {
  id: string;
  department_id: string;
  series: string;
  number: number;
  status: string;
}

export interface KioskDepartment {
  id: string;
  name: string;
}

async function kioskFetch<T>(path: string): Promise<T> {
  const token = getKioskToken();
  if (!token) {
    // The component gates queries on the token, so this guards a race
    // where storage is cleared between render and poll.
    throw new KioskApiError(0, "No kiosk token installed");
  }
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText);
    throw new KioskApiError(response.status, text);
  }
  return response.json() as Promise<T>;
}

/** Waiting queue for the counter's department, ordered by token number. */
export function fetchTokenQueue(departmentId: string): Promise<QueueToken[]> {
  return kioskFetch<QueueToken[]>(
    `/api/v1/tokens/queue/?department_id=${encodeURIComponent(departmentId)}`,
  );
}

export function fetchDepartment(departmentId: string): Promise<KioskDepartment> {
  return kioskFetch<KioskDepartment>(
    `/api/v1/departments/${encodeURIComponent(departmentId)}/`,
  );
}
