/**
 * Demo fixture data for the Medicore dashboard (spec 2026-10-22 §2.6/§4.6).
 *
 * All values are synthetic; names are obviously demo placeholders — no real
 * PHI included. If a live backend supplies real data, the view swaps these
 * fixtures for the live query rather than mixing both.
 *
 * The former stats/donut/KPI/admissions exports were dropped with the
 * shadcn/radix chart migration: the Medicore layout consumes only the
 * exports below (pinned by dashboard.unit.test.ts).
 */

/** Registered today — rendered in the "New patients" table. */
export interface NewPatientRow {
  uhid: string;
  name: string;
  department: string;
  time: string;
  status: "confirmed" | "pending";
}

export const fixtureNewPatients: NewPatientRow[] = [
  {
    uhid: "UHID-26-0001",
    name: "Asha L.",
    department: "General Medicine",
    time: "10:10",
    status: "confirmed",
  },
  {
    uhid: "UHID-26-0002",
    name: "Ravi K.",
    department: "Surgery",
    time: "09:45",
    status: "pending",
  },
  {
    uhid: "UHID-26-0003",
    name: "Mina P.",
    department: "OBGYN",
    time: "09:20",
    status: "confirmed",
  },
  {
    uhid: "UHID-26-0004",
    name: "John D.",
    department: "Paediatrics",
    time: "08:55",
    status: "pending",
  },
  {
    uhid: "UHID-26-0005",
    name: "Sana R.",
    department: "Orthopaedics",
    time: "08:30",
    status: "confirmed",
  },
];

/** Two bordered side-cards beside the OPD hero (exactly two, per §2.6). */
export const fixtureMinis = [
  { label: "IPD occupancy", value: "78%" },
  { label: "Lab orders", value: "203" },
];

/** Two demo events under the calendar. */
export const fixtureCalendarEvents = [
  { time: "09:30", title: "OPD follow-up clinic" },
  { time: "14:00", title: "NQAS assessment meeting" },
];

/** Chart headline (mock's "Total patients" figure). */
export const fixturePatientsTotal = 26710;

/**
 * OPD volume per weekday — dual series: `a` = new, `b` = returning.
 * Kept from the previous dashboard; the chart's only data source.
 */
export const fixtureOpdVolume = [
  { day: "Mon 04", a: 42, b: 38 },
  { day: "Tue 05", a: 58, b: 48 },
  { day: "Wed 06", a: 36, b: 30 },
  { day: "Thu 07", a: 62, b: 52 },
  { day: "Fri 08", a: 44, b: 36 },
  { day: "Sat 09", a: 28, b: 22 },
  { day: "Sun 10", a: 18, b: 14 },
];

/**
 * 6×7 (42) Sunday-first calendar grid for the month containing `date`.
 * Cells outside the month are `null` so the view renders blanks instead of
 * inheriting the next month's days (mock prints a fixed 6-row grid).
 */
export function calendarMonthCells(date: Date): Array<Date | null> {
  const first = new Date(date.getFullYear(), date.getMonth(), 1);
  const last = new Date(date.getFullYear(), date.getMonth() + 1, 0);
  const cells: Array<Date | null> = [];
  for (let i = 0; i < first.getDay(); i += 1) cells.push(null);
  for (let day = 1; day <= last.getDate(); day += 1) {
    cells.push(new Date(date.getFullYear(), date.getMonth(), day));
  }
  while (cells.length < 42) cells.push(null);
  return cells;
}
