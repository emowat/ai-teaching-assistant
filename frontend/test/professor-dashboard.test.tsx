import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProfessorDashboard } from "../src/pages/ProfessorDashboard";
import {
  listProfessorSectionLaunchConfigs,
  replaceProfessorSectionLaunchConfigs,
} from "../src/api/sectionLaunchConfigsApi";
import {
  listProfessorSectionStudents,
  listProfessorSections,
} from "../src/api/professorSectionsApi";

vi.mock("../src/api/professorSectionsApi", () => ({
  listProfessorSections: vi.fn(),
  listProfessorSectionStudents: vi.fn(),
}));

vi.mock("../src/api/sectionLaunchConfigsApi", () => ({
  listProfessorSectionLaunchConfigs: vi.fn(),
  replaceProfessorSectionLaunchConfigs: vi.fn(),
}));

const mockedListProfessorSections = vi.mocked(listProfessorSections);
const mockedListProfessorSectionStudents = vi.mocked(listProfessorSectionStudents);
const mockedListProfessorSectionLaunchConfigs = vi.mocked(listProfessorSectionLaunchConfigs);
const mockedReplaceProfessorSectionLaunchConfigs = vi.mocked(
  replaceProfessorSectionLaunchConfigs,
);

describe("ProfessorDashboard", () => {
  beforeEach(() => {
    mockedListProfessorSections.mockReset();
    mockedListProfessorSectionStudents.mockReset();
    mockedListProfessorSectionLaunchConfigs.mockReset();
    mockedReplaceProfessorSectionLaunchConfigs.mockReset();
  });

  it("loads section roster data and lets the professor inspect students", async () => {
    mockedListProfessorSections.mockResolvedValue([
      {
        section_id: "mit14-fall-001",
        course_id: "mit14",
        course_display_name: "MIT 6.0014",
        display_name: "Section A",
        term: "Fall 2026",
        is_active: true,
        professor_count: 1,
        ta_count: 1,
        student_count: 2,
        created_at: "2026-07-08T00:00:00Z",
        updated_at: "2026-07-08T00:00:00Z",
      },
    ]);
    mockedListProfessorSectionLaunchConfigs.mockResolvedValue([
      {
        launch_id: "workspace",
        label: "Workspace",
        repo_url: "https://github.com/example/coding-rabbit",
        template_url: "",
        default_branch: "main",
        enabled: true,
        sort_order: 0,
      },
    ]);
    mockedListProfessorSectionStudents.mockResolvedValue([
      {
        user_id: "student-1",
        cognito_sub: "cognito-sub-1",
        email: "ada@example.com",
        display_name: "Ada Lovelace",
        membership_status: "active",
        role_in_section: "student",
        session_count: 3,
        last_session_at: "2026-07-08T01:02:03Z",
      },
      {
        user_id: "student-2",
        cognito_sub: "cognito-sub-2",
        email: "grace@example.com",
        display_name: "Grace Hopper",
        membership_status: "active",
        role_in_section: "student",
        session_count: 5,
        last_session_at: "2026-07-08T02:03:04Z",
      },
    ]);

    render(
      <ProfessorDashboard
        onNavigate={vi.fn()}
        allowedViews={["professor"]}
        onSignOut={vi.fn()}
        accessToken="access-token-1"
      />,
    );

    expect(await screen.findByLabelText("Teaching section")).toHaveValue("mit14-fall-001");
    expect(screen.getByText("Section context")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Students use the launch configs in this section to enter the workspace\./i,
      ),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(mockedListProfessorSections).toHaveBeenCalledWith("access-token-1");
      expect(mockedListProfessorSectionLaunchConfigs).toHaveBeenCalledWith(
        "mit14-fall-001",
        "access-token-1",
      );
      expect(mockedListProfessorSectionStudents).toHaveBeenCalledWith(
        "mit14-fall-001",
        "access-token-1",
      );
    });

    screen.getByRole("button", { name: /students/i }).click();

    expect(await screen.findByText("Students for Section A")).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByText("3 sessions")).toBeInTheDocument();
  });

  it("shows launch configs and saves changes from the launches tab", async () => {
    mockedListProfessorSections.mockResolvedValue([
      {
        section_id: "mit14-fall-001",
        course_id: "mit14",
        course_display_name: "MIT 6.0014",
        display_name: "Section A",
        term: "Fall 2026",
        is_active: true,
        professor_count: 1,
        ta_count: 0,
        student_count: 1,
        created_at: "2026-07-08T00:00:00Z",
        updated_at: "2026-07-08T00:00:00Z",
      },
    ]);
    mockedListProfessorSectionLaunchConfigs.mockResolvedValue([
      {
        launch_id: "workspace",
        label: "Workspace",
        repo_url: "https://github.com/example/coding-rabbit",
        template_url: "https://github.com/example/coding-rabbit-template",
        default_branch: "main",
        enabled: true,
        sort_order: 0,
      },
    ]);
    mockedListProfessorSectionStudents.mockResolvedValue([]);
    mockedReplaceProfessorSectionLaunchConfigs.mockResolvedValue([
      {
        launch_id: "workspace",
        label: "Workspace",
        repo_url: "https://github.com/example/coding-rabbit",
        template_url: "https://github.com/example/coding-rabbit-template",
        default_branch: "main",
        enabled: true,
        sort_order: 0,
      },
    ]);

    render(
      <ProfessorDashboard
        onNavigate={vi.fn()}
        allowedViews={["professor"]}
        onSignOut={vi.fn()}
        accessToken="access-token-1"
      />,
    );

    expect(await screen.findByLabelText("Teaching section")).toHaveValue("mit14-fall-001");

    screen.getByRole("button", { name: /launches/i }).click();

    expect(await screen.findByText("Section launch config")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Workspace")).toBeInTheDocument();
    expect(screen.getByText(/launch url:/i)).toBeInTheDocument();

    screen.getByRole("button", { name: /save launch configs/i }).click();

    await waitFor(() => {
      expect(mockedReplaceProfessorSectionLaunchConfigs).toHaveBeenCalledWith(
        "mit14-fall-001",
        "access-token-1",
        expect.arrayContaining([
          expect.objectContaining({
            launch_id: "workspace",
            label: "Workspace",
          }),
        ]),
      );
    });

    expect(await screen.findByText("Saved launch configs.")).toBeInTheDocument();

    screen.getByRole("button", { name: /analytics/i }).click();

    expect(await screen.findByText("Section analytics")).toBeInTheDocument();
    expect(
      screen.getByText(/Analytics cards remain stubbed until the aggregation API lands\./i),
    ).toBeInTheDocument();
  });
});
