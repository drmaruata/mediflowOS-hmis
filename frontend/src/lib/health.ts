/** Health-check API types and fetch helper (architecture doc §5 health probe). */

export interface HealthStatus {
  status: "ok" | "degraded" | "error";
  version?: string;
}

export interface ReadinessStatus {
  status: "ready" | "not_ready";
  database: boolean;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

/** Liveness probe — anonymous, no database access. */
export async function fetchHealth(): Promise<HealthStatus> {
  const response = await fetch(`${API_BASE}/api/v1/health/`);
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`);
  }
  return response.json() as Promise<HealthStatus>;
}

/** Readiness probe — returns 503 if the database is unreachable. */
export async function fetchReadiness(): Promise<ReadinessStatus> {
  const response = await fetch(`${API_BASE}/api/v1/health/ready/`);
  if (!response.ok) {
    throw new Error(`Readiness check failed: ${response.status}`);
  }
  return response.json() as Promise<ReadinessStatus>;
}
