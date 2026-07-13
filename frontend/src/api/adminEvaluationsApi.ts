import { apiGet, apiPost } from "./client.ts";

export type EvaluationJudgeProvider = "openai" | "bedrock";
export type EvaluationRunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "launch_failed";

export interface EvaluationRunScope {
  course_id?: string | null;
  section_id?: string | null;
  start_date?: string | null;
  end_date?: string | null;
}

export interface EvaluationRunMetric {
  metric_id: string;
  evaluation_run_id: string;
  metric_group: string;
  metric_name: string;
  metric_value?: number | null;
  metric_text: string;
  metric_metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface EvaluationRunArtifact {
  artifact_id: string;
  evaluation_run_id: string;
  artifact_type: string;
  label: string;
  s3_uri: string;
  content_type: string;
  artifact_metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface EvaluationRunSummary {
  evaluation_run_id: string;
  run_label: string;
  notes: string;
  requested_by_user_id?: string | null;
  requested_by_cognito_sub: string;
  requested_by_email: string;
  judge_provider: EvaluationJudgeProvider;
  judge_model: string;
  input_dataset_s3_uri: string;
  results_s3_prefix: string;
  course_id?: string | null;
  section_id?: string | null;
  scope_start_date?: string | null;
  scope_end_date?: string | null;
  scope_metadata: Record<string, unknown>;
  status: EvaluationRunStatus;
  message: string;
  total_rows: number;
  usable_rows: number;
  skipped_rows: number;
  macro_pass_rate?: number | null;
  micro_pass_rate?: number | null;
  drift_rate?: number | null;
  quality_decline_rate?: number | null;
  code_leak_rate?: number | null;
  summary: Record<string, unknown>;
  artifacts: EvaluationRunArtifact[];
  metrics: EvaluationRunMetric[];
  ecs_cluster: string;
  ecs_task_definition: string;
  ecs_container_name: string;
  ecs_task_arn?: string | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface EvaluationLaunchConfig {
  default_judge_provider: EvaluationJudgeProvider;
  default_judge_model: string;
  supported_judge_providers: EvaluationJudgeProvider[];
  results_bucket: string;
  results_prefix: string;
  export_timezone: string;
  ecs: {
    cluster: string;
    task_definition: string;
    container_name: string;
    launch_type: string;
    platform_version: string;
    assign_public_ip: string;
    subnet_ids: string[];
    security_group_ids: string[];
  };
}

export interface EvaluationRunCreatePayload {
  judge_provider: EvaluationJudgeProvider;
  judge_model: string;
  dataset_s3_uri?: string | null;
  export_scope?: EvaluationRunScope | null;
  run_label?: string;
  notes?: string;
}

export interface EvaluationOverviewResponse {
  total_runs: number;
  active_runs: number;
  status_counts: Record<string, number>;
  recent_runs: EvaluationRunSummary[];
}

function withQuery(
  path: string,
  query: Record<string, string | number | null | undefined>,
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  const suffix = params.toString();
  return suffix ? `${path}?${suffix}` : path;
}

export function getAdminEvaluationConfig(
  accessToken: string,
): Promise<EvaluationLaunchConfig> {
  return apiGet<EvaluationLaunchConfig>("/api/admin/evaluations/config", accessToken);
}

export function launchAdminEvaluationRun(
  accessToken: string,
  payload: EvaluationRunCreatePayload,
): Promise<EvaluationRunSummary> {
  return apiPost<EvaluationRunCreatePayload, EvaluationRunSummary>(
    "/api/admin/evaluations/runs",
    payload,
    accessToken,
  );
}

export function listAdminEvaluationRuns(
  accessToken: string,
  options?: { limit?: number; status?: string | null },
): Promise<EvaluationRunSummary[]> {
  return apiGet<EvaluationRunSummary[]>(
    withQuery("/api/admin/evaluations/runs", {
      limit: options?.limit ?? 25,
      status: options?.status ?? undefined,
    }),
    accessToken,
  );
}

export function getAdminEvaluationRun(
  accessToken: string,
  runId: string,
): Promise<EvaluationRunSummary> {
  return apiGet<EvaluationRunSummary>(
    `/api/admin/evaluations/runs/${encodeURIComponent(runId)}`,
    accessToken,
  );
}

export function getAdminEvaluationOverview(
  accessToken: string,
  limit = 5,
): Promise<EvaluationOverviewResponse> {
  return apiGet<EvaluationOverviewResponse>(
    withQuery("/api/admin/evaluations/overview", { limit }),
    accessToken,
  );
}
