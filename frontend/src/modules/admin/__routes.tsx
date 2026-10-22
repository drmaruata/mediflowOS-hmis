/**
 * Admin — route surface for the /admin screens (UI_UX_design §7 "Users
 * administration", "Roles administration", "Departments administration",
 * "Wards and beds administration", "Audit log viewer"; TEN-004, TEN-008,
 * AUD-003).
 *
 * Exports lazy elements for the screens; App.tsx keeps the route table
 * itself. The lazy() calls live here so each screen stays its own chunk —
 * App.tsx imports only this thin module eagerly.
 */

import { lazy } from "react";

export const AdminUsers = lazy(() => import("./Users"));
export const AdminRoles = lazy(() => import("./Roles"));
export const AdminDepartmentsWardsBeds = lazy(() => import("./DepartmentsWardsBeds"));
export const AdminAuditLog = lazy(() => import("./AuditLog"));
