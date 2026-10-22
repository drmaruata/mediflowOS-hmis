/**
 * DashboardView — Medicore modern layout (plan 2026-10-22, Task 7).
 *
 * Renders the real view: hero + minis, chart with a working range select,
 * calendar, new-patients table with a working search, and the module strip.
 * Every assertion is fixture-driven so demo-data tweaks cannot break the
 * screen silently. No server data: the old health band moved to AppHeader
 * (Task 4), so no fetch stub or QueryClient is needed here.
 */
import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import DashboardView from "./DashboardView";
import { fixtureNewPatients } from "./dashboard.fixture";

function wrapper() {
  return render(
    <MemoryRouter>
      <DashboardView />
    </MemoryRouter>,
  );
}

describe("DashboardView", () => {
  it("shows the modern panels and the module strip", () => {
    wrapper();
    expect(screen.getByText("Total patients")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "New patients" }),
    ).toBeInTheDocument();
    const strip = screen.getByRole("group", { name: "Module overview" });
    const buttons = within(strip).queryAllByRole("button");
    const links = within(strip).queryAllByRole("link");
    // Ten bounded contexts render; unbuilt ones are honest disabled buttons.
    expect(buttons.length + links.length).toBe(10);
    expect(buttons.every((button) => button.hasAttribute("disabled"))).toBe(
      true,
    );
  });

  it("keeps the demo-data pill", () => {
    wrapper();
    expect(screen.getAllByText(/demo data/i).length).toBeGreaterThanOrEqual(1);
  });

  it("search filters the table rows", async () => {
    const user = userEvent.setup();
    wrapper();
    await user.type(
      screen.getByLabelText(/search patients/i),
      fixtureNewPatients[0].uhid,
    );
    expect(screen.getByText(fixtureNewPatients[0].name)).toBeInTheDocument();
    for (const row of fixtureNewPatients.slice(1)) {
      expect(screen.queryByText(row.name)).toBeNull();
    }
  });

  it("chart range select switches the series length", async () => {
    const user = userEvent.setup();
    wrapper();
    expect(screen.getAllByRole("img")).toHaveLength(7);
    await user.selectOptions(screen.getByLabelText(/chart range/i), "3d");
    expect(screen.getAllByRole("img")).toHaveLength(3);
  });
});
