import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LandingPage } from "../src/pages/LandingPage";

const signinRedirect = vi.fn();

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ signinRedirect }),
}));

vi.mock("../src/auth/cognitoConfig", () => ({
  getRedirectOrigin: () => "https://www.codingrabbit.dev",
  getRedirectUri: () => "https://www.codingrabbit.dev/auth/callback",
  hasOriginMismatch: () => false,
}));

describe("LandingPage", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    signinRedirect.mockReset();
    vi.useFakeTimers();
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      callback(0);
      return 1;
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows a skippable splash and automatically opens the public site", () => {
    render(<LandingPage onNavigate={vi.fn()} />);

    expect(
      screen.getByRole("heading", {
        name: "Get unstuck without giving away the thinking.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip intro" })).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    expect(
      screen.getByRole("heading", {
        name: "Learn C++ without giving away the thinking.",
      }),
    ).toBeInTheDocument();
    expect(window.sessionStorage.getItem("codingrabbit.capstone-intro-seen")).toBe(
      "true",
    );
  });

  it("lets visitors skip immediately and does not repeat within the session", () => {
    const { unmount } = render(<LandingPage onNavigate={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Skip intro" }));

    expect(screen.getByText("The question behind the product")).toBeInTheDocument();
    unmount();

    render(<LandingPage onNavigate={vi.fn()} />);

    expect(
      screen.queryByRole("heading", {
        name: "Get unstuck without giving away the thinking.",
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "What happens to learning when answers become effortless?",
      }),
    ).toBeInTheDocument();
  });

  it("presents the AI-era learning question without the retired terminology", () => {
    window.sessionStorage.setItem("codingrabbit.capstone-intro-seen", "true");
    const { container } = render(<LandingPage onNavigate={vi.fn()} />);

    expect(
      screen.getByText(/when powerful LLM assistance is always available/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Vygotsky's zone of proximal development/i)).toBeInTheDocument();
    expect(screen.getByText(/lightweight behavioral gamification/i)).toBeInTheDocument();
    const retiredTerm = new RegExp(["soc", "ratic"].join(""), "i");
    expect(container.textContent).not.toMatch(retiredTerm);
  });

  it("keeps Cognito sign-in available from the public site", () => {
    window.sessionStorage.setItem("codingrabbit.capstone-intro-seen", "true");
    render(<LandingPage onNavigate={vi.fn()} />);

    fireEvent.click(screen.getAllByRole("button", { name: "Sign in" })[0]);

    expect(signinRedirect).toHaveBeenCalledTimes(1);
  });

  it("shows all team members and sends Try CodingRabbit through Cognito", () => {
    window.sessionStorage.setItem("codingrabbit.capstone-intro-seen", "true");
    render(<LandingPage onNavigate={vi.fn()} />);

    expect(screen.getByText("Carlos Schrupp")).toBeInTheDocument();
    expect(screen.getByText("Alex Alvarez")).toBeInTheDocument();
    expect(screen.getByText("Ligong Zhang")).toBeInTheDocument();
    expect(screen.getByText("Lyn Wang")).toBeInTheDocument();
    expect(screen.getByText("Eric Mowat")).toBeInTheDocument();
    expect(screen.getByText("Infrastructure, AWS backend, and UI")).toBeInTheDocument();
    expect(screen.getByText("Model guardrails")).toBeInTheDocument();
    expect(screen.getByText("RAG pipeline")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Try CodingRabbit" })[0]);

    expect(signinRedirect).toHaveBeenCalledTimes(1);
  });
});
