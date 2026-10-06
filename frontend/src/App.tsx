/**
 * App.tsx — root shell and route table for the Vite React SPA (React Router 7).
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
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { useAuthStore } from "@/stores/authStore";
import { useThemeStore } from "@/stores/themeStore";
import { AppHeader } from "@/components/AppHeader";
import { AppSidebar, AppSidebarDrawer } from "@/components/AppSidebar";
import LoginPage from "@/modules/auth/LoginPage";

const DashboardView = lazy(() => import("@/modules/dashboard/DashboardView"));

const queryClient = new QueryClient({
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
  // No token yet ⇒ sign-in; authenticated ⇒ requested route.
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" replace />;
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
    <div className="min-h-svh bg-canvas-dashboard text-foreground">
      <AppHeader
        isLive={false}
        isCompact={false}
        collapsed={collapsed}
        onOpenNav={() => setDrawerOpen(true)}
        onToggleCollapsed={() => setCollapsed((prev) => !prev)}
      />
      <div className="flex">
        <AppSidebar collapsed={collapsed} />
        <AppSidebarDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
        <main className="min-w-0 flex-1 px-4 py-6 md:px-8">
          <Suspense
            fallback={
              <div className="flex min-h-[60vh] items-center justify-center text-muted-foreground">
                <span>Loading dashboard…</span>
              </div>
            }
          >
            <DashboardView />
          </Suspense>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/"
            element={
              <AuthGuard>
                <AuthLayout />
              </AuthGuard>
            }
          />
          {/* Unknown routes land on the nearest safe parent with a stable
              shell rather than a blank page (UI_UX_design §4.3). */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}