import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import DashboardView from "./DashboardView";

function wrapper() {
  return render(
    <MemoryRouter>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <DashboardView />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("DashboardView", () => {
  it("renders the dashboard title", () => {
    wrapper();
    expect(screen.getByRole("heading", { name: /dashboard/i })).toBeInTheDocument();
  });

  it("shows the demo-data pill by default (prop-driven)", () => {
    wrapper();
    expect(screen.getByText(/demo data/i)).toBeInTheDocument();
  });
});
