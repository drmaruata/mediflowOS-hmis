/**
 * Server-error mapping shared by every form-bearing module (extracted from
 * modules/setup/setup.api.ts when the patient registry needed the same
 * contract — it is API-generic and belongs outside any one module).
 *
 * The server stays the authority: DRF 400 bodies are field maps
 * ({name: ["..."]}) or a detail string; the client maps them back onto the
 * forms field-by-field instead of showing one generic failure.
 */

import { ApiError } from "@/lib/apiClient";

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
