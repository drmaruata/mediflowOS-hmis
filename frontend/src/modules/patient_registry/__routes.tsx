/**
 * Patient registry — route surface for /patients (UI_UX_design §7 "Patient
 * registry — search/register", "Patient profile / UHID" and the
 * verification work list; REG-001..007).
 *
 * Exports lazy elements for the list/registration/detail/queue screens plus
 * the /patients layout they nest under; App.tsx keeps the route table
 * itself (nested routes under /patients). The lazy() calls live here so
 * each screen stays its own chunk — App.tsx imports only this thin module
 * eagerly.
 */

import { lazy } from "react";
import { Outlet } from "react-router-dom";

export const PatientList = lazy(() => import("./PatientList"));
export const PatientRegistration = lazy(() => import("./PatientRegistration"));
export const PatientDetail = lazy(() => import("./PatientDetail"));
export const VerificationQueue = lazy(() => import("./VerificationQueue"));

export default function PatientRegistryRoutes() {
  return <Outlet />;
}
