/**
 * App.tsx — root shell and route table for the Vite React SPA (React Router 7).
 *
 * Route contract: UI_UX_design §4.3/§7/§18.2 — canonical paths /auth/sign-in
 * and /dashboard, with the pre-contract /login and / kept as redirects so
 * existing links and tests keep resolving. Each scaffolded R1 module exports
 * a lazy()-loaded route surface (modules/<name>/__routes.tsx) that later
 * tasks replace with real screens.
 *
 * The authenticated shell follows design.md §5: a 64px global top bar, a
 * 240px persistent navigation rail (72px when collapsed) and the page
 * canvas. Navigation content lives in `@/lib/navigation`; this file is the
 * route table and layout only (AGENTS.md §5).
 *
 * Note: the previous Ant Design `ConfigProvider` is removed; shadcn/ui
 * components use the Tailwind CSS variables in `src/styles/globals.css`.
 */

import { Suspense, lazy, useEffect, useState } from "react";
import {
  BrowserRouter,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { useAuthStore } from "@/stores/authStore";
import { useThemeStore } from "@/stores/themeStore";
import { useSession } from "@/lib/session";
import { AppHeader } from "@/components/AppHeader";
import { AppSidebar, AppSidebarDrawer } from "@/components/AppSidebar";
import { PageHeading } from "@/components/PageHeading";
import LoginPage from "@/modules/auth/LoginPage";
import PatientRegistryRoutes, {
  PatientDetail,
  PatientList,
  PatientRegistration,
  VerificationQueue,
} from "@/modules/patient_registry/__routes";
import OpSlip from "@/modules/print/OpSlip";
import {
  AdminAuditLog,
  AdminDepartmentsWardsBeds,
  AdminRoles,
  AdminUsers,
} from "@/modules/admin/__routes";

const DashboardView = lazy(() => import("@/modules/dashboard/DashboardView"));
const MfaChallenge = lazy(() => import("@/modules/auth/MfaChallenge"));
const SetupRoutes = lazy(() => import("@/modules/setup/__routes"));
const KioskRoutes = lazy(() => import("@/modules/kiosk/__routes"));
const NotificationsRoutes = lazy(() =>
  import("@/modules/notifications/__routes"),
);

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
});

function AuthGuard({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  // No token yet ⇒ sign-in at the canonical route; authenticated ⇒ requested
  // route. /login stays as a redirect for pre-contract links.
  return isAuthenticated ? (
    <>{children}</>
  ) : (
    <Navigate to="/auth/sign-in" replace />
  );
}

/**
 * Second-factor navigation gate (TEN-006): a session whose role demands MFA
 * but has not proven it sees the challenge, never the shell. Acts only on
 * positive session knowledge — MFARequiredIfConfigured on the server remains
 * the enforcement, this is routing.
 */
function MfaGate({ children }: { children: React.ReactNode }) {
  const session = useSession();
  const me = session.data;

  if (me && me.requires_mfa && !me.mfa_verified) {
    return <Navigate to="/mfa" replace />;
  }
  if (!me && session.isPending) {
    return (
      <div
        aria-busy="true"
        className="flex min-h-svh items-center justify-center text-muted-foreground"
      >
        <span>Loading session…</span>
      </div>
    );
  }
  return <>{children}</>;
}

/**
 * Keep `theme=system` honest when the OS flips while the app is open.
 * StrictMode mounts effects twice, so subscribe/unsubscribe must be
 * symmetric and the handler must be idempotent (AGENTS.md §5).
 */
function useSystemThemeSync() {
  const sync = useThemeStore((s) => s.sync);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => sync();
    query.addEventListener("change", onChange);
    // Reconcile once on mount in case the bootstrap ran before storage was
    // readable (e.g. storage blocked until interaction).
    onChange();
    return () => query.removeEventListener("change", onChange);
  }, [sync]);
}

function AuthLayout() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  useSystemThemeSync();

  // Close the mobile drawer on navigation so it cannot cover the new page.
  const location = useLocation();
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  return (
    <div className="min-h-svh bg-shell-sidebar text-foreground">
      {/*
        Full-bleed shell at every width (design decision 2026-10-22: the
        desktop frame from spec §4.10 / the mock was dropped by user
        direction). The page is the shell's only scroll context — rail and
        content column are plain flow children — and the sticky topbar
        keeps controls reachable on tall routes.
      */}
      <div>
        <AppHeader
          isLive={false}
          isCompact={false}
          collapsed={collapsed}
          onOpenNav={() => setDrawerOpen(true)}
          onToggleCollapsed={() => setCollapsed((prev) => !prev)}
        />
        <div className="flex">
          <AppSidebar
            collapsed={collapsed}
            /* At lg the rail is an in-flow stretch child (scrolls with the
               page once); the root's sticky viewport cap stays for md. */
            className="lg:static lg:h-auto"
          />
          <AppSidebarDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
          <main className="min-w-0 flex-1 px-4 py-6 md:px-8 lg:px-6 lg:py-5">
            <PageHeading />
            <Suspense
              fallback={
                <div className="flex min-h-[60vh] items-center justify-center text-muted-foreground">
                  <span>Loading…</span>
                </div>
              }
            >
              <Outlet />
            </Suspense>
          </main>
        </div>
      </div>
    </div>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      {/* Redirects keep the pre-contract paths working (UI_UX §4.3). */}
      <Route path="/login" element={<Navigate to="/auth/sign-in" replace />} />
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/auth/sign-in" element={<LoginPage />} />
      <Route
        path="/mfa"
        element={
          <AuthGuard>
            <Suspense
              fallback={
                <div className="flex min-h-svh items-center justify-center text-muted-foreground">
                  <span>Loading…</span>
                </div>
              }
            >
              <MfaChallenge />
            </Suspense>
          </AuthGuard>
        }
      />
      {/* Kiosk is a standalone wall display — no shell and no login prompt
          (UI_UX §7 kiosk); its scoped read token lands with Task 35. */}
      <Route
        path="/kiosk/tokens/:displayId"
        element={
          <Suspense
            fallback={
              <div className="flex min-h-svh items-center justify-center text-muted-foreground">
                <span>Loading…</span>
              </div>
            }
          >
            <KioskRoutes />
          </Suspense>
        }
      />
      {/* OP slip print view — no app chrome, direct URL access (UI-006, HW-001).
          The API call requires auth and will 401 if unauthenticated, which is
          correct: a patient printing their own slip must be signed in. */}
      <Route
        path="/print/op-slip/:visitId"
        element={
          <Suspense
            fallback={
              <div className="flex min-h-svh items-center justify-center text-muted-foreground">
                <span>Loading…</span>
              </div>
            }
          >
            <OpSlip />
          </Suspense>
        }
      />
      {/* Authenticated shell: nav-item routes render into AuthLayout's
          Outlet; MfaGate still sends an unverified privileged user to /mfa. */}
      <Route
        element={
          <AuthGuard>
            <MfaGate>
              <AuthLayout />
            </MfaGate>
          </AuthGuard>
        }
      >
        <Route path="/dashboard" element={<DashboardView />} />
        <Route path="/admin/setup" element={<SetupRoutes />} />
        {/* The patient registry nests its screens under /patients; the
            module's __routes.tsx owns the lazy screen elements, this table
            owns the paths (UI_UX §7; detail is keyed by the record id the
            backend retrieves by, not the UHID). */}
        <Route path="/patients" element={<PatientRegistryRoutes />}>
          <Route index element={<PatientList />} />
          <Route path="register" element={<PatientRegistration />} />
          <Route path="verification-queue" element={<VerificationQueue />} />
          <Route path=":id" element={<PatientDetail />} />
        </Route>
        {/* Admin screens (UI_UX §7): users/roles/configuration are flat
            routes under /admin; the departments and wards-beds paths share
            the one configuration edit surface, which renders the sections
            each nav item names. */}
        <Route path="/admin/users" element={<AdminUsers />} />
        <Route path="/admin/roles" element={<AdminRoles />} />
        <Route
          path="/admin/departments"
          element={<AdminDepartmentsWardsBeds section="departments" />}
        />
        <Route
          path="/admin/wards-beds"
          element={<AdminDepartmentsWardsBeds section="wards-beds" />}
        />
        <Route path="/admin/audit" element={<AdminAuditLog />} />
        <Route path="/notifications" element={<NotificationsRoutes />} />
      </Route>
      {/* Unknown routes land on the nearest safe parent with a stable
          shell rather than a blank page (UI_UX_design §4.3). */}
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}