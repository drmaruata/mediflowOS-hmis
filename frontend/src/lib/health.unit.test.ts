import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchApiHealth } from "./health";

afterEach(() => vi.unstubAllGlobals());

describe("fetchApiHealth", () => {
  it("returns the API health response", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: "ok", version: "0.1.0" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchApiHealth()).resolves.toEqual({ status: "ok", version: "0.1.0" });
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/health/");
  });

  it("rejects when the backend returns an error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));

    await expect(fetchApiHealth()).rejects.toThrow("Backend unavailable");
  });
});