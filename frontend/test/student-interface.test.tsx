import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StudentInterface } from "../src/pages/StudentInterface";
import { getStudentBootstrap } from "../src/api/studentBootstrapApi";

vi.mock("../src/api/studentBootstrapApi", () => ({
  getStudentBootstrap: vi.fn(),
}));

const mockedGetStudentBootstrap = vi.mocked(getStudentBootstrap);

describe("StudentInterface", () => {
  beforeEach(() => {
    mockedGetStudentBootstrap.mockReset();
  });

  it("loads the active section and opens the configured launch target", async () => {
    mockedGetStudentBootstrap.mockResolvedValue({
      user: {
        app_user_id: "user-1",
        cognito_sub: "cognito-sub-1",
        email: "student@example.com",
        display_name: "Student One",
        primary_role: "student",
        status: "active",
      },
      default_section_id: "mit14-fall-001",
      endpoints: {
        chat: "/api/chat",
        telemetry: "/api/telemetry",
        feedback: "/api/feedback",
      },
      sections: [
        {
          section_id: "mit14-fall-001",
          course_id: "mit14",
          course_display_name: "MIT 6.0014",
          display_name: "Section A",
          term: "Fall 2026",
          is_active: true,
          membership_status: "active",
          launch_configs: [
            {
              launch_id: "starter",
              label: "Starter",
              repo_url: "",
              template_url: "",
              default_branch: "main",
              enabled: false,
              sort_order: 0,
            },
            {
              launch_id: "workspace",
              label: "Workspace",
              repo_url: "https://github.com/example/coding-rabbit",
              template_url: "",
              default_branch: "student",
              enabled: true,
              sort_order: 1,
            },
          ],
        },
        {
          section_id: "mit14-fall-002",
          course_id: "mit14",
          course_display_name: "MIT 6.0014",
          display_name: "Section B",
          term: "Fall 2026",
          is_active: true,
          membership_status: "active",
          launch_configs: [
            {
              launch_id: "backup",
              label: "Backup",
              repo_url: "https://github.com/example/backup",
              template_url: "",
              default_branch: "main",
              enabled: true,
              sort_order: 0,
            },
          ],
        },
      ],
    });

    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);

    render(
      <StudentInterface
        onNavigate={vi.fn()}
        allowedViews={["student"]}
        onSignOut={vi.fn()}
        accessToken="access-token-1"
      />,
    );

    expect(
      await screen.findByRole("heading", {
        name: /launch your section-specific codespace/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Active section")).toHaveValue("mit14-fall-001");
    expect(screen.getByLabelText("Launch target")).toHaveValue("workspace");

    screen.getByRole("button", { name: /open launch target/i }).click();

    await waitFor(() => {
      expect(openSpy).toHaveBeenCalledTimes(1);
    });

    const [launchUrl, target, features] = openSpy.mock.calls[0] as [
      string,
      string,
      string,
    ];
    const parsedUrl = new URL(launchUrl);

    expect(target).toBe("_blank");
    expect(features).toBe("noopener,noreferrer");
    expect(parsedUrl.origin).toBe("https://codespaces.new");
    expect(parsedUrl.pathname).toBe("/example/coding-rabbit");
    expect(parsedUrl.searchParams.get("quickstart")).toBe("1");
    expect(parsedUrl.searchParams.get("ref")).toBe("student");
  });

  it("shows the access error state when bootstrap fails", async () => {
    mockedGetStudentBootstrap.mockRejectedValue(new Error("Access denied"));

    render(
      <StudentInterface
        onNavigate={vi.fn()}
        allowedViews={["student"]}
        onSignOut={vi.fn()}
        accessToken="access-token-1"
      />,
    );

    expect(await screen.findByText("Student access unavailable")).toBeInTheDocument();
    expect(screen.getByText("Access denied")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry student access/i })).toBeInTheDocument();
  });
});
