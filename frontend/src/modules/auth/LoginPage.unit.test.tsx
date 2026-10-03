import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LoginPage from "./LoginPage";

describe("LoginPage", () => {
  it("renders the login card and title", () => {
    render(
      <MemoryRouter>
        <QueryClientProvider
          client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        >
          <LoginPage />
        </QueryClientProvider>
      </MemoryRouter>,
    );
    expect(screen.getByText("Mediflow OS")).toBeInTheDocument();
    expect(screen.getByLabelText(/email.*user id/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
  });
});
