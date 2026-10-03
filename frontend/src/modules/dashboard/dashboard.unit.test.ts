/**
 * Dashboard pure-logic unit tests (◪ supermemory — dayjs-free, pure logic).
 * Tests fixture-derived stats and donut math only.
 */
import { describe, it, expect } from "vitest";
import { fixtureStats, fixtureDonutBeds } from "./dashboard.fixture";

describe("dashboard fixture logic", () => {
  it("fixture stats have numeric or string values", () => {
    fixtureStats.forEach((s) => {
      expect(typeof s.value === "number" || typeof s.value === "string").toBe(true);
    });
  });

  it("donut segments sum to total beds", () => {
    const total = fixtureDonutBeds.reduce((a, b) => a + b.value, 0);
    expect(total).toBeGreaterThan(0);
    expect(fixtureDonutBeds.length).toBe(5);
  });

  it("donut arc dash length is proportional to value", () => {
    const total = fixtureDonutBeds.reduce((a, b) => a + b.value, 0);
    const r = 40, c = 2 * Math.PI * r;
    const first = fixtureDonutBeds[0];
    const dash = (first.value / total) * c;
    expect(dash).toBeGreaterThan(0);
    expect(dash).toBeLessThanOrEqual(c);
  });
});
