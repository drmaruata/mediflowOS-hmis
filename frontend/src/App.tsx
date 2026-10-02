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
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
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
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const [collapsed, setCollapsed] = React.useState(false);
  const isCompact = true;
  return (
    <div className="min-h-svh bg-background text-foreground">
      <AppHeader
        isLive={false}
        isCompact={isCompact}
        collapsed={collapsed}
        onOpenNav={isCompact ? () => setDrawerOpen(true) : undefined}
        onToggleCollapsed={isCompact ? undefined : () => setCollapsed((p) => !p)}
      />
      {drawerOpen && (
        <aside className="fixed inset-y-0 left-0 z-50 w-64 bg-card border-r shadow-xl p-4" aria-label="Navigation drawer">
          <button onClick={() => setDrawerOpen(false)} className="mb-4 text-sm underline">Close</button>
          <nav>Dashboard · Auth · Settings</nav>
        </aside>
      )}
      <main className="mx-auto max-w-7xl px-4 md:px-6">
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
