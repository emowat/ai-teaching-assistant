import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminDashboard } from "../src/pages/AdminDashboard";
import { checkGradioAvailable, getGradioUrl } from "../src/api/gradioApi";
import {
  getAdminLlmConfig,
  getAdminDashboardFeedback,
  getAdminDashboardStats,
  restartBackend,
  saveAdminLlmConfig,
} from "../src/api/adminLlmApi";
import { listAdminCourses } from "../src/api/adminCoursesApi";

vi.mock("../src/api/gradioApi", () => ({
  checkGradioAvailable: vi.fn(),
  getGradioUrl: vi.fn(() => "http://localhost:8001/gradio/"),
}));

vi.mock("../src/api/adminLlmApi", () => ({
  getAdminLlmConfig: vi.fn(),
  getAdminDashboardStats: vi.fn(),
  getAdminDashboardFeedback: vi.fn(),
  saveAdminLlmConfig: vi.fn(),
  restartBackend: vi.fn(),
}));

vi.mock("../src/api/adminCoursesApi", () => ({
  listAdminCourses: vi.fn(),
}));

vi.mock("../src/components/admin/UserManagementPanel", () => ({
  UserManagementPanel: () => <div>Mock Users Panel</div>,
}));

vi.mock("../src/components/admin/SectionManagementPanel", () => ({
  SectionManagementPanel: () => <div>Mock Sections Panel</div>,
}));

vi.mock("../src/components/admin/CourseManagementPanel", () => ({
  CourseManagementPanel: () => <div>Mock Courses Panel</div>,
}));

vi.mock("../src/components/admin/RagDocsPanel", () => ({
  RagDocsPanel: () => <div>Mock RAG Panel</div>,
}));

vi.mock("../src/components/admin/OfflineEvalsPanel", () => ({
  OfflineEvalsPanel: () => <div>Mock Offline Evals Panel</div>,
}));

const mockedCheckGradioAvailable = vi.mocked(checkGradioAvailable);
const mockedGetGradioUrl = vi.mocked(getGradioUrl);
const mockedGetAdminLlmConfig = vi.mocked(getAdminLlmConfig);
const mockedGetAdminDashboardStats = vi.mocked(getAdminDashboardStats);
const mockedGetAdminDashboardFeedback = vi.mocked(getAdminDashboardFeedback);
const mockedListAdminCourses = vi.mocked(listAdminCourses);
const mockedSaveAdminLlmConfig = vi.mocked(saveAdminLlmConfig);
const mockedRestartBackend = vi.mocked(restartBackend);

describe("AdminDashboard", () => {
  beforeEach(() => {
    mockedCheckGradioAvailable.mockReset();
    mockedGetGradioUrl.mockReset();
    mockedGetAdminLlmConfig.mockReset();
    mockedGetAdminDashboardStats.mockReset();
    mockedGetAdminDashboardFeedback.mockReset();
    mockedListAdminCourses.mockReset();
    mockedSaveAdminLlmConfig.mockReset();
    mockedRestartBackend.mockReset();

    mockedCheckGradioAvailable.mockResolvedValue(true);
    mockedGetGradioUrl.mockReturnValue("http://localhost:8001/gradio/");
    mockedGetAdminLlmConfig.mockResolvedValue({
      rag: { provider: "cohere", model: "command-xlarge-nightly" },
      chat: { provider: "ollama", model: "qwen3.5:9b" },
      openai_api_key_configured: false,
      openai_base_url: "https://api.openai.com/v1",
      restart_command_configured: true,
    });
    mockedGetAdminDashboardStats.mockResolvedValue({
      sessions_today: 0,
      requests_today: 0,
      total_rewards_given: 0,
      total_style_nudges: 0,
      chat_seconds_today: 0,
      editor_seconds_today: 0,
      terminal_seconds_today: 0,
      weekly_rewards: [],
      weekly_engagement: [],
      session_data: [],
      homework_keys: [],
      study_keys: [],
      model_share: [],
      evaluation_model_share: [],
      guardrails: {
        input_blocks: 0,
        output_blocks: 0,
        input_dry_runs: 0,
        output_dry_runs: 0,
        violation_types: [],
      },
      latencies: {
        rag: { p50: 0, p90: 0, p99: 0 },
        llm: { p50: 0, p90: 0, p99: 0 },
        input_guardrail: { p50: 0, p90: 0, p99: 0 },
        output_guardrail: { p50: 0, p90: 0, p99: 0 },
      },
      retry_health_pct: 100,
      system_errors: 0,
      status: "ok",
    });
    mockedGetAdminDashboardFeedback.mockResolvedValue({ feedback: [] });
    mockedListAdminCourses.mockResolvedValue([]);
    mockedSaveAdminLlmConfig.mockResolvedValue({
      rag: { provider: "cohere", model: "command-xlarge-nightly" },
      chat: { provider: "ollama", model: "qwen3.5:9b" },
      openai_api_key_configured: false,
      openai_base_url: "https://api.openai.com/v1",
      restart_command_configured: true,
    });
    mockedRestartBackend.mockResolvedValue({
      success: true,
      scheduled: true,
      message: "Restart scheduled.",
    });
  });

  it("shows Sections in the admin navigation and opens the section management panel", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        ready: true,
        qdrant_configured: true,
        course_registry_configured: true,
        cohere_configured: true,
        openai_configured: true,
        bedrock_configured: true,
        qdrant_reachable: true,
        course_registry_reachable: true,
        cohere_reachable: true,
        openai_reachable: true,
        bedrock_reachable: true,
        message: "Ready.",
      }),
      text: async () => "",
    } as Response);

    render(
      <AdminDashboard
        onNavigate={vi.fn()}
        allowedViews={["admin"]}
        onSignOut={vi.fn()}
        accessToken="access-token-1"
      />,
    );

    expect(await screen.findByRole("button", { name: /sections/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /classes/i })).not.toBeInTheDocument();

    screen.getByRole("button", { name: /sections/i }).click();

    expect(await screen.findByText("Mock Sections Panel")).toBeInTheDocument();
    await waitFor(() => {
      expect(mockedCheckGradioAvailable).toHaveBeenCalled();
      expect(mockedGetAdminLlmConfig).toHaveBeenCalledWith("access-token-1");
      expect(mockedListAdminCourses).toHaveBeenCalledWith("access-token-1");
    });

    fetchMock.mockRestore();
  });

  it("shows Offline Evals in the admin navigation and opens the eval panel", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        ready: true,
        qdrant_configured: true,
        course_registry_configured: true,
        cohere_configured: true,
        openai_configured: true,
        bedrock_configured: true,
        qdrant_reachable: true,
        course_registry_reachable: true,
        cohere_reachable: true,
        openai_reachable: true,
        bedrock_reachable: true,
        message: "Ready.",
      }),
      text: async () => "",
    } as Response);

    render(
      <AdminDashboard
        onNavigate={vi.fn()}
        allowedViews={["admin"]}
        onSignOut={vi.fn()}
        accessToken="access-token-1"
      />,
    );

    expect(await screen.findByRole("button", { name: /offline evals/i })).toBeInTheDocument();

    screen.getByRole("button", { name: /offline evals/i }).click();

    expect(await screen.findByText("Mock Offline Evals Panel")).toBeInTheDocument();

    fetchMock.mockRestore();
  });
});
