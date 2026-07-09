import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProfessorDashboard } from "../src/pages/ProfessorDashboard";
import { getProfessorSectionAnalytics } from "../src/api/professorSectionsApi";
import {
  listProfessorSectionLaunchConfigs,
  replaceProfessorSectionLaunchConfigs,
} from "../src/api/sectionLaunchConfigsApi";
import {
  listProfessorSectionStudents,
  listProfessorSections,
} from "../src/api/professorSectionsApi";
import {
  archiveProfessorTeachingPlan,
  createProfessorTeachingPlanWeek,
  deleteProfessorTeachingPlanWeek,
  getProfessorTeachingPlan,
  publishProfessorTeachingPlan,
  saveProfessorTeachingPlan,
  updateProfessorTeachingPlanWeek,
} from "../src/api/teachingPlanApi";

vi.mock("../src/api/professorSectionsApi", () => ({
  getProfessorSectionAnalytics: vi.fn(),
  listProfessorSections: vi.fn(),
  listProfessorSectionStudents: vi.fn(),
}));

vi.mock("../src/api/sectionLaunchConfigsApi", () => ({
  listProfessorSectionLaunchConfigs: vi.fn(),
  replaceProfessorSectionLaunchConfigs: vi.fn(),
}));

vi.mock("../src/api/teachingPlanApi", () => ({
  archiveProfessorTeachingPlan: vi.fn(),
  createProfessorTeachingPlanWeek: vi.fn(),
  deleteProfessorTeachingPlanWeek: vi.fn(),
  getProfessorTeachingPlan: vi.fn(),
  publishProfessorTeachingPlan: vi.fn(),
  saveProfessorTeachingPlan: vi.fn(),
  updateProfessorTeachingPlanWeek: vi.fn(),
}));

const mockedListProfessorSections = vi.mocked(listProfessorSections);
const mockedGetProfessorSectionAnalytics = vi.mocked(getProfessorSectionAnalytics);
const mockedListProfessorSectionStudents = vi.mocked(listProfessorSectionStudents);
const mockedListProfessorSectionLaunchConfigs = vi.mocked(listProfessorSectionLaunchConfigs);
const mockedReplaceProfessorSectionLaunchConfigs = vi.mocked(
  replaceProfessorSectionLaunchConfigs,
);
const mockedGetProfessorTeachingPlan = vi.mocked(getProfessorTeachingPlan);
const mockedSaveProfessorTeachingPlan = vi.mocked(saveProfessorTeachingPlan);
const mockedPublishProfessorTeachingPlan = vi.mocked(publishProfessorTeachingPlan);
const mockedArchiveProfessorTeachingPlan = vi.mocked(archiveProfessorTeachingPlan);
const mockedCreateProfessorTeachingPlanWeek = vi.mocked(createProfessorTeachingPlanWeek);
const mockedUpdateProfessorTeachingPlanWeek = vi.mocked(updateProfessorTeachingPlanWeek);
const mockedDeleteProfessorTeachingPlanWeek = vi.mocked(deleteProfessorTeachingPlanWeek);

describe("ProfessorDashboard", () => {
  beforeEach(() => {
    mockedGetProfessorSectionAnalytics.mockReset();
    mockedListProfessorSections.mockReset();
    mockedListProfessorSectionStudents.mockReset();
    mockedListProfessorSectionLaunchConfigs.mockReset();
    mockedReplaceProfessorSectionLaunchConfigs.mockReset();
    mockedGetProfessorTeachingPlan.mockReset();
    mockedSaveProfessorTeachingPlan.mockReset();
    mockedPublishProfessorTeachingPlan.mockReset();
    mockedArchiveProfessorTeachingPlan.mockReset();
    mockedCreateProfessorTeachingPlanWeek.mockReset();
    mockedUpdateProfessorTeachingPlanWeek.mockReset();
    mockedDeleteProfessorTeachingPlanWeek.mockReset();
    mockedGetProfessorSectionAnalytics.mockResolvedValue({
      section: {
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
      sessions_last_7_days: 8,
      active_students_last_7_days: 2,
      weekly_activity: [
        { day: "Mon", sessions: 1, active_students: 1 },
        { day: "Tue", sessions: 0, active_students: 0 },
        { day: "Wed", sessions: 2, active_students: 2 },
        { day: "Thu", sessions: 1, active_students: 1 },
        { day: "Fri", sessions: 3, active_students: 2 },
        { day: "Sat", sessions: 1, active_students: 1 },
        { day: "Sun", sessions: 0, active_students: 0 },
      ],
      top_students: [
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
      ],
      generated_at: "2026-07-08T00:00:00Z",
    });
    mockedGetProfessorTeachingPlan.mockResolvedValue({
      teaching_plan_id: null,
      section_id: "mit14-fall-001",
      version: 1,
      status: "draft",
      title: "",
      summary: "",
      created_by_user_id: null,
      published_by_user_id: null,
      published_at: null,
      weeks: [],
      created_at: "",
      updated_at: "",
    });
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
      expect(mockedGetProfessorSectionAnalytics).toHaveBeenCalledWith(
        "mit14-fall-001",
        "access-token-1",
      );
    });

    screen.getByRole("button", { name: /students/i }).click();

    expect(await screen.findByText("Students for Section A")).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByText("3 sessions")).toBeInTheDocument();

    screen.getByRole("button", { name: /analytics/i }).click();

    expect(await screen.findByText("Section analytics")).toBeInTheDocument();
    expect(screen.getByText("// sessions_7d")).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
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
      screen.getByText(/Live Aurora-backed analytics for the selected section\./i),
    ).toBeInTheDocument();
  });

  it("shows a teaching plan editor and persists plan and week updates", async () => {
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
    mockedListProfessorSectionLaunchConfigs.mockResolvedValue([]);
    mockedListProfessorSectionStudents.mockResolvedValue([]);
    mockedGetProfessorTeachingPlan.mockResolvedValue({
      teaching_plan_id: "plan-1",
      section_id: "mit14-fall-001",
      version: 1,
      status: "draft",
      title: "Pointer Safety",
      summary: "Week-by-week plan",
      created_by_user_id: "prof-1",
      published_by_user_id: null,
      published_at: null,
      weeks: [
        {
          week_id: "week-1",
          teaching_plan_id: "plan-1",
          week_number: 1,
          title: "C Basics",
          topic: "Pointers",
          start_date: null,
          end_date: null,
          learning_objectives: ["Trace pointer lifetimes"],
          instructional_guidance: "Keep it concrete.",
          status: "draft",
          created_at: "2026-06-20T00:00:00Z",
          updated_at: "2026-06-20T00:00:00Z",
        },
      ],
      created_at: "2026-06-20T00:00:00Z",
      updated_at: "2026-06-20T00:00:00Z",
    });
    mockedSaveProfessorTeachingPlan.mockResolvedValue({
      teaching_plan_id: "plan-1",
      section_id: "mit14-fall-001",
      version: 1,
      status: "draft",
      title: "Pointer Safety Updated",
      summary: "Week-by-week plan",
      created_by_user_id: "prof-1",
      published_by_user_id: null,
      published_at: null,
      weeks: [
        {
          week_id: "week-1",
          teaching_plan_id: "plan-1",
          week_number: 1,
          title: "C Basics",
          topic: "Pointers",
          start_date: null,
          end_date: null,
          learning_objectives: ["Trace pointer lifetimes"],
          instructional_guidance: "Keep it concrete.",
          status: "draft",
          created_at: "2026-06-20T00:00:00Z",
          updated_at: "2026-06-20T00:00:00Z",
        },
      ],
      created_at: "2026-06-20T00:00:00Z",
      updated_at: "2026-06-20T00:00:00Z",
    });
    mockedCreateProfessorTeachingPlanWeek.mockResolvedValue({
      teaching_plan_id: "plan-1",
      section_id: "mit14-fall-001",
      version: 1,
      status: "draft",
      title: "Pointer Safety Updated",
      summary: "Week-by-week plan",
      created_by_user_id: "prof-1",
      published_by_user_id: null,
      published_at: null,
      weeks: [
        {
          week_id: "week-1",
          teaching_plan_id: "plan-1",
          week_number: 1,
          title: "C Basics",
          topic: "Pointers",
          start_date: null,
          end_date: null,
          learning_objectives: ["Trace pointer lifetimes"],
          instructional_guidance: "Keep it concrete.",
          status: "draft",
          created_at: "2026-06-20T00:00:00Z",
          updated_at: "2026-06-20T00:00:00Z",
        },
        {
          week_id: "week-2",
          teaching_plan_id: "plan-1",
          week_number: 2,
          title: "Week 2",
          topic: "",
          start_date: null,
          end_date: null,
          learning_objectives: [],
          instructional_guidance: "",
          status: "draft",
          created_at: "2026-06-20T00:00:00Z",
          updated_at: "2026-06-20T00:00:00Z",
        },
      ],
      created_at: "2026-06-20T00:00:00Z",
      updated_at: "2026-06-20T00:00:00Z",
    });
    mockedUpdateProfessorTeachingPlanWeek.mockResolvedValue({
      teaching_plan_id: "plan-1",
      section_id: "mit14-fall-001",
      version: 1,
      status: "draft",
      title: "Pointer Safety Updated",
      summary: "Week-by-week plan",
      created_by_user_id: "prof-1",
      published_by_user_id: null,
      published_at: null,
      weeks: [
        {
          week_id: "week-1",
          teaching_plan_id: "plan-1",
          week_number: 1,
          title: "C Basics",
          topic: "Pointers and stack memory",
          start_date: null,
          end_date: null,
          learning_objectives: ["Trace pointer lifetimes"],
          instructional_guidance: "Keep it concrete.",
          status: "draft",
          created_at: "2026-06-20T00:00:00Z",
          updated_at: "2026-06-20T00:00:00Z",
        },
      ],
      created_at: "2026-06-20T00:00:00Z",
      updated_at: "2026-06-20T00:00:00Z",
    });
    mockedDeleteProfessorTeachingPlanWeek.mockResolvedValue({
      teaching_plan_id: "plan-1",
      section_id: "mit14-fall-001",
      version: 1,
      status: "draft",
      title: "Pointer Safety Updated",
      summary: "Week-by-week plan",
      created_by_user_id: "prof-1",
      published_by_user_id: null,
      published_at: null,
      weeks: [],
      created_at: "2026-06-20T00:00:00Z",
      updated_at: "2026-06-20T00:00:00Z",
    });

    render(
      <ProfessorDashboard
        onNavigate={vi.fn()}
        allowedViews={["professor"]}
        onSignOut={vi.fn()}
        accessToken="access-token-1"
      />,
    );

    expect(await screen.findByLabelText("Teaching section")).toHaveValue("mit14-fall-001");

    screen.getByRole("button", { name: /teaching plan/i }).click();

    expect(await screen.findByText(/Teaching Plan for Section A/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Plan title")).toHaveValue("Pointer Safety");
    expect(screen.getByLabelText("Plan summary")).toHaveValue("Week-by-week plan");
    expect(screen.getByDisplayValue("C Basics")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Plan title"), {
      target: { value: "Pointer Safety Updated" },
    });

    screen.getByRole("button", { name: /save plan/i }).click();

    await waitFor(() => {
      expect(mockedSaveProfessorTeachingPlan).toHaveBeenCalledWith(
        "mit14-fall-001",
        "access-token-1",
        expect.objectContaining({ title: "Pointer Safety Updated" }),
      );
    });

    fireEvent.change(screen.getByDisplayValue("Pointers"), {
      target: { value: "Pointers and stack memory" },
    });

    screen.getByRole("button", { name: /save week/i }).click();

    await waitFor(() => {
      expect(mockedUpdateProfessorTeachingPlanWeek).toHaveBeenCalledWith(
        "mit14-fall-001",
        "week-1",
        "access-token-1",
        expect.objectContaining({ topic: "Pointers and stack memory" }),
      );
    });

    screen.getByRole("button", { name: /add week/i }).click();

    await waitFor(() => {
      expect(mockedCreateProfessorTeachingPlanWeek).toHaveBeenCalledWith(
        "mit14-fall-001",
        "access-token-1",
        expect.objectContaining({ week_number: 2 }),
      );
    });
  });
});
