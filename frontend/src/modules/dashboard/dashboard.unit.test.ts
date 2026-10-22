/**
 * Dashboard fixture contracts for the Medicore rebuild (plan 2026-10-22,
 * Task 7). Synthetic values only — no real PHI. These tests pin the shape
 * the view consumes (rows/status type, mini count, calendar grid math,
 * chart series) so demo-data tweaks cannot silently break the screen.
 */
import { describe, it, expect } from "vitest";
import {
  calendarMonthCells,
  fixtureMinis,
  fixtureNewPatients,
  fixtureOpdVolume,
  fixturePatientsTotal,
} from "./dashboard.fixture";

describe("dashboard fixture logic", () => {
  it("new-patient rows are unique and status-typed", () => {
    expect(fixtureNewPatients.length).toBeGreaterThanOrEqual(5);
    const uhids = fixtureNewPatients.map((row) => row.uhid);
    expect(new Set(uhids).size).toBe(uhids.length);
    for (const row of fixtureNewPatients) {
      expect(["confirmed", "pending"]).toContain(row.status);
    }
  });

  it("minis are exactly two with unique labels", () => {
    expect(fixtureMinis).toHaveLength(2);
    expect(new Set(fixtureMinis.map((mini) => mini.label)).size).toBe(2);
  });

  it("calendarMonthCells lays out six Sunday-first weeks, each day once", () => {
    const month = new Date(2026, 9, 22);
    const cells = calendarMonthCells(month);
    expect(cells).toHaveLength(42);

    // Leading blanks equal the first day's weekday index (Sunday-first).
    const leading = cells.findIndex((cell) => cell !== null);
    expect(leading).toBe(new Date(2026, 9, 1).getDay());
    for (let i = 0; i < leading; i += 1) expect(cells[i]).toBeNull();

    // October has 31 days — each date appears exactly once, in the month,
    // and the blanks only pad before day 1 and after the month's last day.
    const days = cells.filter((cell) => cell !== null);
    expect(days).toHaveLength(31);
    for (let day = 1; day <= 31; day += 1) {
      const matches = cells.filter((cell) => cell?.getDate() === day);
      expect(matches).toHaveLength(1);
      expect(matches[0]?.getMonth()).toBe(9);
    }
  });

  it("opd volume carries seven dual series of positive integers", () => {
    expect(fixtureOpdVolume).toHaveLength(7);
    for (const row of fixtureOpdVolume) {
      expect(Number.isInteger(row.a) && row.a > 0).toBe(true);
      expect(Number.isInteger(row.b) && row.b > 0).toBe(true);
    }
  });

  it("patients total matches the chart headline", () => {
    expect(fixturePatientsTotal).toBe(26710);
  });
});
