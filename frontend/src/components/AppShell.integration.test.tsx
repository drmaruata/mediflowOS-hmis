/**
 * AppShell (AppSidebar + AppHeader) — component flow coverage.
 *
 * Spec: design.md §5.2/§5.3/§23, §2.3A, UI_UX_design §12 (accessible
 * names, no colour-only state).
 *
 * These assert user-visible output via role/name queries rather than
 * implementation internals (AGENTS.md §6).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppHeader } from "./AppHeader";
import { AppSidebar } from "./AppSidebar";
import { useThemeStore } from "@/stores/themeStore";

function renderWithProviders(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.classList.remove("dark");
});

describe("AppSidebar", () => {
  it("renders the grouped navigation with its section headings", () => {
    renderWithProviders(<AppSidebar />);
    expect(
      screen.getByRole("navigation", { name: "Primary" }),
    ).toBeInTheDocument();
    for (const label of ["Main Menu", "Settings"]) {
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

  it("does not colour the rail with theme-scoped sidebar tokens", () => {
    // Regression guard: `--sidebar-*` follows the theme, but the rail surface
    // is fixed navy in both themes. Using the theme-scoped pair made labels
    // render dark-navy-on-navy in light mode.
    const { container } = renderWithProviders(<AppSidebar />);
    const rail = container.querySelector("aside");
    expect(rail).not.toBeNull();
    const html = rail?.outerHTML ?? "";
    expect(html).toContain("bg-shell-sidebar");
    expect(html).toMatch(/text-shell-sidebar-/);
    expect(html).not.toMatch(/text-sidebar-foreground/);
    expect(html).not.toMatch(/bg-sidebar-accent/);
  });

  it("exposes the rail as a named complementary landmark", () => {
    renderWithProviders(<AppSidebar />);
    expect(
      screen.getByRole("complementary", { name: "Main navigation" }),
    ).toBeInTheDocument();
  });

  it("links Dashboard and marks it as the current page", () => {
    renderWithProviders(<AppSidebar />);
    const link = screen.getByRole("link", { name: "Dashboard" });
    expect(link).toHaveAttribute("href", "/");
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
      <MemoryRouter>
        <AppHeader isLive />
      </MemoryRouter>,
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