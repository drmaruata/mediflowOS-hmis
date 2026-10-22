/**
 * AppShell (AppSidebar + AppHeader) — component flow coverage.
 *
 * Spec: design.md §5.2/§5.3/§23, §2.3A, UI_UX_design §12 (accessible
 * names, no colour-only state).
 *
 * These assert user-visible output via role/name queries rather than
 * implementation internals (AGENTS.md §6).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";

import { AppRoutes } from "@/App";
import { AppHeader } from "./AppHeader";
import { AppSidebar } from "./AppSidebar";
import { useAuthStore } from "@/stores/authStore";
import { useThemeStore } from "@/stores/themeStore";

function renderWithProviders(
  ui: React.ReactElement,
  initialEntries?: string[],
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.classList.remove("dark");
});

describe("AppSidebar", () => {
  // The theme store is module-scoped: reset to System so a previous test's
  // Dark choice cannot bleed into the aria-pressed assertions below.
  beforeEach(() => {
    useThemeStore.getState().setPreference("system");
  });

  it("renders the grouped navigation with its section headings", () => {
    renderWithProviders(<AppSidebar />);
    expect(
      screen.getByRole("navigation", { name: "Primary" }),
    ).toBeInTheDocument();
    for (const label of ["Main Menu", "Configuration & setups"]) {
      expect(screen.getByRole("heading", { name: label })).toBeInTheDocument();
    }
  });

  it("lists every backend module so the sidebar is the build backlog", () => {
    renderWithProviders(<AppSidebar />);
    for (const label of [
      "Dashboard",
      "Patient Registration",
      "OPD",
      "IPD",
      "EMR",
      "Emergency",
      "ICU & Live Vitals",
      "Operation Theatre",
      "Laboratory (LIS)",
      "Radiology (RIS)",
      "Pharmacy & Store",
      "Blood Bank",
      "Insurance",
      "Billing",
      "Tariffs",
      "Claims & TPA",
      "Quality OS",
      "CAPA",
      "Data Quality",
      "Alerts",
      "Assessments (NQAS/NABH)",
      "Reports & Exports",
      "Users & Roles",
      "Departments",
      "Wards & Beds",
      "Facility Setup",
      "Configuration History",
      "Registration Config",
      "Quality Profile",
      "ABDM / QR",
      "Audit",
      "Notifications",
      "ABDM Exchange",
      "Integrations",
      "Platform Tenants",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("renders the Medicore brand block and a chip for the rail codes", () => {
    renderWithProviders(<AppSidebar />);
    expect(screen.getByText("Mediflow")).toBeInTheDocument();
    expect(screen.getByText("Hospital Information System")).toBeInTheDocument();
    // Chips replace icons (Medicore spec §2.3/§4.9). They are decorative
    // duplication of the label — aria-hidden — so each link's accessible
    // name stays exactly its label for screen readers.
    for (const code of ["DB", "PR", "OP", "IP", "EM", "ER", "IC", "OT"]) {
      expect(screen.getByText(code)).toHaveAttribute("aria-hidden", "true");
    }
  });

  it("paints the rail from chrome tokens — no white utilities", () => {
    // Inverse of the old fixed-navy guard: the Medicore chrome is
    // theme-scoped (styles.unit.test asserts both blocks), so the remaining
    // component-level failure mode is an invisible white-on-light-rail
    // control left over from the navy rail.
    const { container } = renderWithProviders(<AppSidebar />);
    const rail = container.querySelector("aside");
    expect(rail).not.toBeNull();
    const html = rail?.outerHTML ?? "";
    expect(html).toContain("bg-shell-sidebar");
    expect(html).toMatch(/text-shell-sidebar-/);
    expect(html).not.toMatch(/text-white/);
    expect(html).not.toMatch(/bg-white/);
  });

  it("exposes the rail as a named complementary landmark", () => {
    renderWithProviders(<AppSidebar />);
    expect(
      screen.getByRole("complementary", { name: "Main navigation" }),
    ).toBeInTheDocument();
  });

  it("links Dashboard and marks it as the current page", () => {
    renderWithProviders(<AppSidebar />, ["/dashboard"]);
    const link = screen.getByRole("link", { name: "Dashboard" });
    expect(link).toHaveAttribute("href", "/dashboard");
    expect(link).toHaveAttribute("aria-current", "page");
  });

  it("does not link entries whose route does not exist yet", () => {
    renderWithProviders(<AppSidebar />);
    // OPD is R2 and unwired — a link here would render a blank content area.
    expect(screen.queryByRole("link", { name: "OPD" })).not.toBeInTheDocument();
    expect(screen.getByText("OPD")).toBeInTheDocument();
  });

  it("gives disabled entries an accessible name, not colour alone", () => {
    renderWithProviders(<AppSidebar />);
    const opd = screen.getByText("OPD").closest("[aria-disabled]");
    expect(opd).not.toBeNull();
    expect(opd).toHaveAttribute("aria-disabled", "true");
    expect(opd?.getAttribute("title")).toMatch(/Not enabled|Not available/);
  });

  it("keeps labels available to assistive tech when collapsed", () => {
    renderWithProviders(<AppSidebar collapsed />);
    // Icon-only rail: the link text is still the accessible name.
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Main Menu" })).toBeNull();
    // The chip stands in for the icon on the 72px rail.
    expect(screen.getByText("DB")).not.toHaveClass("sr-only");
  });

  it("offers Light, Dark and System in the footer switcher", () => {
    renderWithProviders(<AppSidebar />);
    expect(
      screen.getByRole("group", { name: "Theme selection" }),
    ).toBeInTheDocument();
    for (const label of ["Light", "Dark", "System"]) {
      const button = screen.getByRole("button", { name: label });
      expect(button).toHaveAttribute(
        "aria-pressed",
        String(
          useThemeStore.getState().preference === label.toLowerCase(),
        ),
      );
    }
  });

  it("switching to Dark persists an explicit preference", () => {
    renderWithProviders(<AppSidebar />);
    fireEvent.click(screen.getByRole("button", { name: "Dark" }));
    expect(useThemeStore.getState().preference).toBe("dark");
    // The store applies the resolved theme to the document element.
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("renders the real stack as the version line, not fake release data", () => {
    renderWithProviders(<AppSidebar />);
    expect(
      screen.getByText("Mediflow OS · React 18 · Django 5.2"),
    ).toBeInTheDocument();
  });
});

describe("AppHeader", () => {
  it("shows the brand, context selectors and an accessible search field", () => {
    renderWithProviders(
      <AppHeader onOpenNav={vi.fn()} onToggleCollapsed={vi.fn()} />,
    );
    expect(screen.getByText("Mediflow OS")).toBeInTheDocument();
    expect(screen.getByLabelText("Tenant")).toBeInTheDocument();
    expect(screen.getByLabelText("Facility")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Search patient by UHID, name, phone or ABHA"),
    ).toBeInTheDocument();
  });

  it("exposes the Ctrl+K shortcut hint", () => {
    renderWithProviders(<AppHeader />);
    expect(screen.getByText("Ctrl K")).toBeInTheDocument();
  });

  it("gives every icon-only control an accessible name", () => {
    renderWithProviders(
      <AppHeader onOpenNav={vi.fn()} onToggleCollapsed={vi.fn()} />,
    );
    for (const name of [
      "Open navigation",
      "Collapse sidebar",
      "Notifications",
      "User menu",
    ]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("labels the collapse toggle according to state", () => {
    renderWithProviders(
      <AppHeader collapsed onOpenNav={vi.fn()} onToggleCollapsed={vi.fn()} />,
    );
    expect(
      screen.getByRole("button", { name: "Expand sidebar" }),
    ).toBeInTheDocument();
  });

  it("surfaces the data-source state as text, not colour alone", () => {
    const { rerender } = renderWithProviders(<AppHeader />);
    expect(screen.getByText("Demo data")).toBeInTheDocument();

    rerender(
      <QueryClientProvider
        client={new QueryClient({
          defaultOptions: { queries: { retry: false } },
        })}
      >
        <MemoryRouter>
          <AppHeader isLive />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByText("Live Data")).toBeInTheDocument();
  });

  it("exposes a theme control reflecting the current preference", () => {
    renderWithProviders(<AppHeader />);
    const button = screen.getByRole("button", { name: /Theme:/ });
    expect(button).toBeInTheDocument();
    expect(button.getAttribute("aria-label")).toMatch(/Theme: (light|dark|system)/);
  });

  it("keeps the resolved theme reflected on the document element", () => {
    useThemeStore.getState().setPreference("dark");
    renderWithProviders(<AppHeader />);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});

describe("route contract (UI_UX §4.3/§18.2)", () => {
  // MemoryRouter keeps the URL out of window.history; the probe makes the
  // router's post-redirect location assertable next to the real routes.
  function LocationProbe() {
    const { pathname } = useLocation();
    return <p>Current path: {pathname}</p>;
  }

  beforeEach(() => {
    useAuthStore.setState({
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
    });
  });

  it("redirects the legacy /login path to the canonical /auth/sign-in", async () => {
    renderWithProviders(
      <>
        <AppRoutes />
        <LocationProbe />
      </>,
      ["/login"],
    );

    expect(await screen.findByLabelText(/email.*user id/i)).toBeInTheDocument();
    expect(
      screen.getByText("Current path: /auth/sign-in"),
    ).toBeInTheDocument();
  });

  it("renders the dashboard at the canonical /dashboard route", async () => {
    useAuthStore.setState({
      accessToken: "access-1",
      refreshToken: "refresh-1",
      isAuthenticated: true,
    });
    const okJson = (body: unknown): Response =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/auth/me/")) {
          return okJson({
            username: "clerk-a",
            tenant_id: null,
            facility_id: null,
            role: "clerk",
            permissions: ["patient_registry.view_patient"],
            allows_break_glass: false,
            requires_mfa: false,
            mfa_verified: true,
          });
        }
        if (url.endsWith("/health/")) return okJson({ status: "ok" });
        return okJson({});
      }),
    );

    renderWithProviders(
      <>
        <AppRoutes />
        <LocationProbe />
      </>,
      ["/dashboard"],
    );

    expect(await screen.findByText(/Welcome back/)).toBeInTheDocument();
    expect(screen.getByText("Current path: /dashboard")).toBeInTheDocument();
  });
});