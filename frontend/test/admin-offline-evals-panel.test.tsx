import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OfflineEvalsPanel } from "../src/components/admin/OfflineEvalsPanel";
import {
  getAdminEvaluationConfig,
  getAdminEvaluationOverview,
  launchAdminEvaluationRun,
  listAdminEvaluationRuns,
} from "../src/api/adminEvaluationsApi";
import { listAdminCourses } from "../src/api/adminCoursesApi";
import { listAdminSections } from "../src/api/adminSectionsApi";

vi.mock("../src/api/adminEvaluationsApi", () => ({
  getAdminEvaluationConfig: vi.fn(),
  getAdminEvaluationOverview: vi.fn(),
  launchAdminEvaluationRun: vi.fn(),
  listAdminEvaluationRuns: vi.fn(),
}));

vi.mock("../src/api/adminCoursesApi", () => ({
  listAdminCourses: vi.fn(),
}));

vi.mock("../src/api/adminSectionsApi", () => ({
  listAdminSections: vi.fn(),
}));

const mockedGetAdminEvaluationConfig = vi.mocked(getAdminEvaluationConfig);
const mockedGetAdminEvaluationOverview = vi.mocked(getAdminEvaluationOverview);
const mockedLaunchAdminEvaluationRun = vi.mocked(launchAdminEvaluationRun);
const mockedListAdminEvaluationRuns = vi.mocked(listAdminEvaluationRuns);
const mockedListAdminCourses = vi.mocked(listAdminCourses);
const mockedListAdminSections = vi.mocked(listAdminSections);

describe("OfflineEvalsPanel", () => {
  const evaluationRunSummary = {
    evaluation_run_id: "run-123",
    run_label: "Weekly eval",
    notes: "Section review",
    requested_by_user_id: "user-1",
    requested_by_cognito_sub: "admin-sub",
    requested_by_email: "admin@example.edu",
    judge_provider: "bedrock" as const,
    judge_model: "anthropic.claude-haiku-4-5",
    input_dataset_s3_uri: "s3://codingrabbit-data-dev/evaluation/offline/run-123/input/turn_snapshots.jsonl",
    results_s3_prefix: "s3://codingrabbit-data-dev/evaluation/offline/run-123/results",
    course_id: "mit14",
    section_id: "mit14-fall-001",
    scope_start_date: "2026-07-01",
    scope_end_date: "2026-07-07",
    scope_metadata: { export_scope: { course_id: "mit14" } },
    status: "running" as const,
    message: "Launched.",
    total_rows: 10,
    usable_rows: 9,
    skipped_rows: 1,
    macro_pass_rate: 0.8,
    micro_pass_rate: 0.75,
    drift_rate: 0.1,
    quality_decline_rate: 0.05,
    code_leak_rate: 0.0,
    summary: { overall: "ok" },
    artifacts: [],
    metrics: [],
    ecs_cluster: "codingrabbit-rag-eng",
    ecs_task_definition: "codingrabbit-evaluation-worker",
    ecs_container_name: "evaluation-worker",
    ecs_task_arn: "arn:aws:ecs:us-east-1:123456789012:task/abc123",
    created_at: "2026-07-13T00:00:00Z",
    updated_at: "2026-07-13T00:00:00Z",
    started_at: "2026-07-13T00:05:00Z",
    completed_at: null,
  };

  beforeEach(() => {
    mockedGetAdminEvaluationConfig.mockReset();
    mockedGetAdminEvaluationOverview.mockReset();
    mockedLaunchAdminEvaluationRun.mockReset();
    mockedListAdminEvaluationRuns.mockReset();
    mockedListAdminCourses.mockReset();
    mockedListAdminSections.mockReset();

    mockedGetAdminEvaluationConfig.mockResolvedValue({
      default_judge_provider: "bedrock",
      default_judge_model: "anthropic.claude-haiku-4-5",
      supported_judge_providers: ["openai", "bedrock"],
      results_bucket: "codingrabbit-data-dev",
      results_prefix: "evaluation/offline",
      export_timezone: "America/Los_Angeles",
      ecs: {
        cluster: "codingrabbit-rag-eng",
        task_definition: "codingrabbit-evaluation-worker",
        container_name: "evaluation-worker",
        launch_type: "FARGATE",
        platform_version: "LATEST",
        assign_public_ip: "ENABLED",
        subnet_ids: ["subnet-a"],
        security_group_ids: ["sg-a"],
      },
    });
    mockedGetAdminEvaluationOverview.mockResolvedValue({
      total_runs: 1,
      active_runs: 0,
      status_counts: { succeeded: 1 },
      recent_runs: [],
    });
    mockedListAdminEvaluationRuns.mockResolvedValueOnce([]).mockResolvedValueOnce([evaluationRunSummary]);
    mockedListAdminCourses.mockResolvedValue([
      {
        course_id: "mit14",
        display_name: "MIT 6.0014",
        course_source: "mit14",
        collection_name: "codingrabbit_rag_vectordb",
        is_active: true,
        has_ingestion_history: true,
        aliases: [],
        syllabus_matrix: "",
        style_guide: "",
        created_at: "2026-07-09T00:00:00Z",
        updated_at: "2026-07-09T00:00:00Z",
      },
    ]);
    mockedListAdminSections.mockResolvedValue([
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
        memberships: [],
        created_at: "2026-07-09T00:00:00Z",
        updated_at: "2026-07-09T00:00:00Z",
      },
    ]);
    mockedLaunchAdminEvaluationRun.mockResolvedValue(evaluationRunSummary);
  });

  it("renders launch controls and recent runs, then launches a new eval", async () => {
    render(<OfflineEvalsPanel accessToken="access-token-1" />);

    expect(await screen.findByText("Offline Evals")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /launch evaluation/i })).toBeInTheDocument();
    expect(await screen.findByText("Recent runs")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Amazon Nova 2 Lite" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Anthropic Claude Sonnet 4.6" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Anthropic Claude Haiku 4.5" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Judge provider"), {
      target: { value: "bedrock" },
    });
    const judgeModelSelect = screen.getByLabelText("Judge model");
    expect(judgeModelSelect).toHaveValue("us.anthropic.claude-haiku-4-5-20251001-v1:0");
    fireEvent.change(judgeModelSelect, {
      target: { value: "us.anthropic.claude-sonnet-4-6" },
    });
    fireEvent.change(screen.getByLabelText("Dataset mode"), {
      target: { value: "direct" },
    });
    const datasetUriInput = await screen.findByLabelText("Dataset S3 URI");
    fireEvent.change(datasetUriInput, {
      target: { value: "s3://codingrabbit-data-dev/evaluation/offline/run-123/input/turn_snapshots.jsonl" },
    });
    fireEvent.change(screen.getByLabelText("Run label"), {
      target: { value: "Weekly eval" },
    });
    fireEvent.change(screen.getByLabelText("Notes"), {
      target: { value: "Section review" },
    });

    fireEvent.click(screen.getByRole("button", { name: /launch evaluation/i }));

    await waitFor(() => {
      expect(mockedLaunchAdminEvaluationRun).toHaveBeenCalledWith(
        "access-token-1",
        expect.objectContaining({
          judge_provider: "bedrock",
          judge_model: "us.anthropic.claude-sonnet-4-6",
          run_label: "Weekly eval",
          notes: "Section review",
        }),
      );
    });

    expect(await screen.findByRole("button", { name: /weekly eval/i })).toBeInTheDocument();
  });
});
