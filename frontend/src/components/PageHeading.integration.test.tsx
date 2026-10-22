/**
 * PageHeading — route-derived page header (Medicore restyle, spec §4.8).
 *
 * One h1 per route: the title resolves from the nav model (exact path, then
 * longest `path + "/"` prefix, else the title-cased first segment). Breadcrumb
 * links home on non-dashboard routes; the module chip carries the nav code;
 * the date pill is a real <time> element — never the mock's fake button.
 *
 * The dashboard route keeps the title "Welcome back" with no breadcrumb and
 * no chip — AppShell's route test pins that exact heading text.
 */

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { PageHeading } from "./PageHeading";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <PageHeading />
    </MemoryRouter>,
  );
}

describe("PageHeading", () => {
  it("renders the dashboard title without breadcrumb or module chip", () => {
    renderAt("/dashboard");
    expect(
      screen.getByRole("heading", { level: 1, name: "Welcome back" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByText("DB")).toBeNull();
  });

  it("renders breadcrumb, route title and chip for a nav route", () => {
    renderAt("/patients");
    expect(
      screen.getByRole("heading", { level: 1, name: "Patient Registration" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute(
      "href",
      "/dashboard",
    );
    expect(screen.getByText("PR")).toBeInTheDocument();
  });

  it("falls back to the longest nav prefix for sub-routes", () => {
    // /patients/123 is a detail route: the registry prefix names the page.
    renderAt("/patients/123");
    expect(
      screen.getByRole("heading", { level: 1, name: "Patient Registration" }),
    ).toBeInTheDocument();
  });

  it("falls back to the title-cased segment when nothing matches", () => {
    renderAt("/admin/roles");
    expect(
      screen.getByRole("heading", { level: 1, name: "Admin" }),
    ).toBeInTheDocument();
  });

  it("exposes the current date as a <time> element", () => {
    const { container } = renderAt("/dashboard");
    const time = container.querySelector("time");
    expect(time).not.toBeNull();
    expect(time?.getAttribute("datetime")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
