import { API_BASE_URL } from "./client";

export type LlmProvider = "cohere" | "openai" | "ollama" | "sagemaker" | "bedrock";

export interface LlmRouteConfig {
  provider: LlmProvider;
  model: string;
}

export interface AdminLlmConfig {
  rag: LlmRouteConfig;
  chat: LlmRouteConfig;
  openai_api_key_configured: boolean;
  openai_base_url: string;
  restart_command_configured: boolean;
}

export interface AdminLlmConfigUpdate {
  rag: LlmRouteConfig;
  chat: LlmRouteConfig;
  openai_api_key?: string | null;
  openai_base_url?: string | null;
}

export interface RestartResponse {
  success: boolean;
  scheduled: boolean;
  message: string;
}

async function adminFetch<T>(
  path: string,
  accessToken: string,
  init?: RequestInit
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    throw new Error(`API error ${response.status}: ${await response.text()}`);
  }

  return response.json() as Promise<T>;
}

export function getAdminLlmConfig(accessToken: string): Promise<AdminLlmConfig> {
  return adminFetch<AdminLlmConfig>("/admin/llm/config", accessToken);
}

export function saveAdminLlmConfig(
  payload: AdminLlmConfigUpdate,
  accessToken: string
): Promise<AdminLlmConfig> {
  return adminFetch<AdminLlmConfig>("/admin/llm/config", accessToken, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function restartBackend(accessToken: string): Promise<RestartResponse> {
  return adminFetch<RestartResponse>("/admin/restart", accessToken, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export interface DashboardStats {
  sessions_today: number;
  requests_today: number;
  total_rewards_given: number;
  total_style_nudges: number;
  chat_seconds_today: number;
  editor_seconds_today: number;
  terminal_seconds_today: number;
  weekly_rewards: { day: string; rewards_given: number; style_nudges: number }[];
  weekly_engagement: { day: string; chat_seconds: number; editor_seconds: number; terminal_seconds: number }[];
  session_data: { day: string; sessions: number; [key: string]: string | number }[];
  homework_keys: string[];
  study_keys: string[];
  model_share: { name: string; value: number }[];
  guardrails: {
    input_blocks: number;
    output_blocks: number;
    input_dry_runs: number;
    output_dry_runs: number;
    violation_types: { name: string; value: number }[];
  };
  latencies: {
    rag: { p50: number; p90: number; p99: number };
    llm: { p50: number; p90: number; p99: number };
    input_guardrail: { p50: number; p90: number; p99: number };
    output_guardrail: { p50: number; p90: number; p99: number };
  };
  retry_health_pct: number;
  system_errors: number;
  status: string;
}

export function getAdminDashboardStats(accessToken: string, courseId?: string, tz?: string): Promise<DashboardStats> {
  const params = new URLSearchParams();
  if (courseId && courseId !== "all") params.append("course_id", courseId);
  if (tz) params.append("tz", tz);
  const qs = params.toString() ? `?${params.toString()}` : "";
  return adminFetch<DashboardStats>(`/api/admin/dashboard/stats${qs}`, accessToken);
}

export interface ChatLogExportResponse {
  partitions: Record<string, unknown>[];
  total_records: number;
  message: string;
}

export function triggerChatLogExport(
  accessToken: string,
  courseId?: string,
  startDate?: string,
  endDate?: string,
  tz?: string
): Promise<ChatLogExportResponse> {
  const params = new URLSearchParams();
  if (courseId && courseId !== "all") params.append("course_id", courseId);
  if (startDate) params.append("start_date", startDate);
  if (endDate) params.append("end_date", endDate);
  if (tz) params.append("tz", tz);

  const qs = params.toString() ? `?${params.toString()}` : "";
  return adminFetch<ChatLogExportResponse>(`/api/admin/export-chat-logs${qs}`, accessToken, {
    method: "POST"
  });
}

export interface FeedbackEntry {
  created_at: string;
  session_id: string;
  turn_index: number;
  rating: "positive" | "negative";
  explanation: string | null;
  student_message: string | null;
  ai_message: string | null;
  cot: Record<string, string>;
  rag_sources: string[];
}

export interface FeedbackResponse {
  feedback: FeedbackEntry[];
}

export function getAdminDashboardFeedback(
  accessToken: string, 
  courseId?: string, 
  limit: number = 50,
  startDate?: string,
  endDate?: string,
  tz: string = Intl.DateTimeFormat().resolvedOptions().timeZone
): Promise<FeedbackResponse> {
  const params = new URLSearchParams();
  if (courseId && courseId !== "all") params.append("course_id", courseId);
  params.append("limit", limit.toString());
  if (startDate) params.append("start_date", startDate);
  if (endDate) params.append("end_date", endDate);
  if (tz) params.append("tz", tz);
  const qs = `?${params.toString()}`;
  return adminFetch<FeedbackResponse>(`/api/admin/dashboard/feedback${qs}`, accessToken);
}
