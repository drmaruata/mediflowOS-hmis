export interface ApiHealth {
  status: string;
  version: string;
}

export async function fetchApiHealth(): Promise<ApiHealth> {
  const response = await fetch("/api/v1/health/");
  if (!response.ok) throw new Error("Backend unavailable");
  return response.json() as Promise<ApiHealth>;
}