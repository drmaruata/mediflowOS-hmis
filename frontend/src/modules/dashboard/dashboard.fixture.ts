/**
 * Demo fixture data for dashboard charts and stats (◪ [2026-10-02]).
 *
 * All values are synthetic; no real PHI is included. This file is the source
 * for the dashboard demo cards — if a live backend returns different numbers,
 * the component should swap to the live query.
 */

export interface FixtureStat {
  label: string;
  value: number | string;
  delta?: number;
  deltaDirection?: "up" | "down" | "neutral";
}

export const fixtureStats: FixtureStat[] = [
  { label: "OPD Registrations", value: 124, delta: 8 },
  { label: "IPD Occupancy", value: "78%", delta: -2 },
  { label: "Lab Orders", value: 203, delta: 14 },
  { label: "Active Patients", value: 91, delta: 3 },
];

export const fixtureDonutBeds = [
  { name: "General", value: 42 },
  { name: "ICU", value: 10 },
  { name: "Maternity", value: 8 },
  { name: "Paediatric", value: 8 },
  { name: "Available", value: 19 },
];
