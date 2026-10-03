/**
 * App.tsx — root shell for the Vite React SPA (React Router 7).
 *
 * Only this file and `src/styles/index.css` may change outside of
 * `src/modules/dashboard/` per the file-boundary rule (◪ [2026-10-02]).
 *
 * Note: the previous Ant Design `ConfigProvider` is removed; shadcn/ui
 * components use Tailwind CSS variables defined in `src/styles/globals.css`.
 */

import React, { Suspense, lazy } from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { useAuthStore } from "@/stores/authStore";
import { AppHeader } from "@/components/AppHeader";
import LoginPage from "@/modules/auth/LoginPage";

const DashboardView = lazy(
  () => import("@/modules/dashboard/DashboardView")
);

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
  // If no token yet, show login; after auth, redirect to dashboard.
  return isAuthenticated ? (
    <>{children}</>
  ) : (
    <Navigate to="/login" replace />
  );
}

function AuthLayout() {
  const location = useLocation();
  const isDashboard = location.pathname === "/";
  const isCompact = false;
  return (
    <div className="min-h-svh bg-muted text-foreground">
      <AppHeader
        isLive={false}
        isCompact={isCompact}
        collapsed={false}
        onOpenNav={undefined}
        onToggleCollapsed={undefined}
      />
      {!isDashboard && (
        <aside
          className="fixed inset-y-0 left-0 z-50 w-72 border-r bg-sidebar p-4 text-sidebar-foreground"
          aria-label="Navigation"
        >
          <nav className="flex flex-col gap-3 text-sm">
            <div>Dashboard</div>
            <div>Auth</div>
            <div>Settings</div>
          </nav>
        </aside>
      )}
      <main className={`mx-auto px-4 md:px-8 py-6 ${isDashboard ? "max-w-[1440px]" : "max-w-7xl ml-72"}`}>
        <Suspense
          fallback={
            <div className="flex min-h-[60vh] items-center justify-center text-muted-foreground">
              <span>Loading dashboard�</span>
            </div>
          }
        >
          <DashboardView />
        </Suspense>
      </main>
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
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}