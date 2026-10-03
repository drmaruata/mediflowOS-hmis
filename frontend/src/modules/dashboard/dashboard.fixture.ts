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

// ——— Extended fixtures for the 1536×1024 reference dashboard (design.md §8) ———

export interface KpiCard {
  label: string;
  value: string;
  delta: string;
  deltaLabel: string;
  trend: "up" | "down" | "neutral";
  spark: number[];
}

export const fixtureKpis: KpiCard[] = [
  { label: "Total Patients", value: "26,710", delta: "↑ 12%", deltaLabel: "vs. 23,864 last month", trend: "up", spark: [18, 22, 15, 28, 20, 32, 26, 30] },
  { label: "OPD Visits", value: "1,842", delta: "↑ 8%", deltaLabel: "vs. yesterday", trend: "up", spark: [12, 18, 14, 22, 16, 24, 20, 26] },
  { label: "Admitted Patients", value: "342", delta: "↑ 4%", deltaLabel: "vs. yesterday", trend: "up", spark: [10, 14, 11, 18, 13, 20, 16, 19] },
  { label: "Emergency Cases", value: "87", delta: "↓ 3%", deltaLabel: "vs. yesterday", trend: "down", spark: [20, 16, 22, 14, 18, 12, 15, 10] },
  { label: "Lab Tests", value: "1,204", delta: "↑ 6%", deltaLabel: "vs. yesterday", trend: "up", spark: [14, 16, 12, 20, 15, 22, 18, 24] },
  { label: "Pending Claims", value: "48", delta: "↓ 5%", deltaLabel: "vs. last week", trend: "down", spark: [22, 18, 20, 14, 16, 10, 12, 8] },
];

export const fixtureBedOccupancy = [
  { name: "Occupied", value: 410, color: "#0F766E" },
  { name: "Available", value: 90, color: "#CBD5E1" },
  { name: "Blocked", value: 18, color: "#94A3B8" },
  { name: "Maintenance", value: 2, color: "#E2E8F0" },
];

export const fixtureOpdVolume = [
  { day: "Mon 04", a: 42, b: 38 },
  { day: "Tue 05", a: 58, b: 48 },
  { day: "Wed 06", a: 36, b: 30 },
  { day: "Thu 07", a: 62, b: 52 },
  { day: "Fri 08", a: 44, b: 36 },
  { day: "Sat 09", a: 28, b: 22 },
  { day: "Sun 10", a: 18, b: 14 },
];

export const fixtureEmergencyAcuity = [
  { name: "Critical", value: 12, color: "#B91C1C" },
  { name: "Urgent", value: 28, color: "#EA580C" },
  { name: "Moderate", value: 34, color: "#CA8A04" },
  { name: "Minor", value: 13, color: "#15803D" },
];

export const fixtureEmergencyFlow = [
  { label: "Waiting", value: 18 },
  { label: "In Treatment", value: 24 },
  { label: "Discharged", value: 45 },
];

export interface OtRow {
  time: string;
  ot: string;
  procedure: string;
  patient: string;
  surgeon: string;
  status: "Ongoing" | "Up Next" | "Scheduled";
}

export const fixtureOtSchedule: OtRow[] = [
  { time: "08:00", ot: "OT-1", procedure: "Laparoscopic Cholecystectomy", patient: "Patient A · 42/F", surgeon: "Dr. Sharma", status: "Ongoing" },
  { time: "09:30", ot: "OT-2", procedure: "Cataract Surgery", patient: "Patient B · 67/M", surgeon: "Dr. Rao", status: "Up Next" },
  { time: "10:00", ot: "OT-1", procedure: "Hernia Repair", patient: "Patient C · 38/M", surgeon: "Dr. Singh", status: "Scheduled" },
  { time: "11:15", ot: "OT-3", procedure: "Caesarean Section", patient: "Patient D · 29/F", surgeon: "Dr. Patel", status: "Scheduled" },
  { time: "13:00", ot: "OT-2", procedure: "Knee Arthroscopy", patient: "Patient E · 51/M", surgeon: "Dr. Verma", status: "Scheduled" },
];

export interface AlertItem {
  title: string;
  detail: string;
  time: string;
  severity: "critical" | "warning" | "info";
}

export const fixtureAlerts: AlertItem[] = [
  { title: "ICU Bed Availability Low", detail: "Only 4 beds available across ICU units.", time: "10:12 AM", severity: "critical" },
  { title: "High Risk Lab Result", detail: "Hb 6.8 g/dL — Patient UHID-000124.", time: "09:48 AM", severity: "critical" },
  { title: "Pending Insurance Approval", detail: "12 PMJAY claims pending beyond 48h.", time: "09:20 AM", severity: "warning" },
  { title: "Equipment Maintenance Due", detail: "X-Ray Unit-2 calibration overdue by 2 days.", time: "08:55 AM", severity: "warning" },
  { title: "Pharmacy Stock Alert", detail: "Amoxicillin 500mg below reorder level.", time: "08:30 AM", severity: "info" },
];

export interface AdmissionRow {
  time: string;
  uhid: string;
  name: string;
  ageSex: string;
  department: string;
  type: string;
  status: string;
}

export const fixtureAdmissions: AdmissionRow[] = [
  { time: "10:10", uhid: "ZMC-000124", name: "Asha L.", ageSex: "42/F", department: "Medicine", type: "IPD", status: "Admitted" },
  { time: "09:45", uhid: "ZMC-000118", name: "Ravi K.", ageSex: "55/M", department: "Surgery", type: "IPD", status: "Admitted" },
  { time: "09:20", uhid: "ZMC-000132", name: "Mina P.", ageSex: "29/F", department: "OBGYN", type: "IPD", status: "Discharged" },
  { time: "08:55", uhid: "ZMC-000101", name: "John D.", ageSex: "61/M", department: "Cardiology", type: "IPD", status: "Admitted" },
];

export const fixtureFunnel = [
  { stage: "Registered", count: 1842, pct: 100 },
  { stage: "Seen by Doctor", count: 1420, pct: 77 },
  { stage: "Investigations", count: 820, pct: 45 },
  { stage: "Admitted", count: 342, pct: 19 },
  { stage: "Discharged", count: 298, pct: 16 },
];

export interface DeptRow {
  department: string;
  opd: number;
  ipd: number;
  occupancy: number;
  status: "Normal" | "High";
}

export const fixtureDepartments: DeptRow[] = [
  { department: "General Medicine", opd: 420, ipd: 88, occupancy: 78, status: "Normal" },
  { department: "Surgery", opd: 310, ipd: 62, occupancy: 82, status: "High" },
  { department: "Paediatrics", opd: 280, ipd: 44, occupancy: 64, status: "Normal" },
  { department: "OBGYN", opd: 260, ipd: 71, occupancy: 91, status: "High" },
  { department: "Orthopaedics", opd: 180, ipd: 38, occupancy: 58, status: "Normal" },
];
