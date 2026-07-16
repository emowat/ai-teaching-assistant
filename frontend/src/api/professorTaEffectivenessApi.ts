import { apiGet, apiPost } from "./client.ts";
import type { ProfessorSectionStudent, ProfessorSectionSummary } from "./professorSectionsApi.ts";
import type { EvaluationJudgeProvider, EvaluationRunSummary } from "./adminEvaluationsApi.ts";

export interface TaEffectivenessMetricResult {
  value: number | string | null;
  reason: string;
}

export interface TaEffectivenessSessionScore {
  session_id: string;
  evaluation_run_id: string;
  mode: string;
  session_effectiveness_score: number | null;
  session_passed: boolean | null;
  macro_metric_results: Record<string, TaEffectivenessMetricResult>;
  pedagogical_impact_score: number | null;
  turn_count: number;
  drift_delta: number | null;
  drift_flag: boolean;
  code_leak_turn_index: number | null;
  scored_at: string;
}

export interface TaEffectivenessTurnScore {
  turn_id: string;
  turn_index: number | null;
  mode: string;
  pedagogical_turn_score: number | null;
  turn_passed: boolean | null;
  micro_metric_results: Record<string, TaEffectivenessMetricResult>;
  input_action: string;
  output_action: string;
}

export interface TaEffectivenessRosterEntry {
  student: ProfessorSectionStudent;
  session_count: number;
  avg_session_effectiveness: number | null;
  avg_pedagogical_impact: number | null;
  drift_rate: number | null;
  has_code_leak: boolean;
  last_scored_at: string;
}

export interface TaEffectivenessSectionRoster {
  section: ProfessorSectionSummary;
  entries: TaEffectivenessRosterEntry[];
  generated_at: string;
}

export interface TaEffectivenessStudentDetail {
  section: ProfessorSectionSummary;
  student: ProfessorSectionStudent;
  sessions: TaEffectivenessSessionScore[];
}

export interface TaEffectivenessSessionTurns {
  session_id: string;
  turns: TaEffectivenessTurnScore[];
}

export interface TaEffectivenessRefreshPayload {
  judge_provider?: EvaluationJudgeProvider | null;
  judge_model?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  run_label?: string;
}

export function taEffectivenessRosterPath(sectionId: string): string {
  return `/professor/sections/${encodeURIComponent(sectionId)}/ta-effectiveness`;
}

export function getTaEffectivenessRoster(
  sectionId: string,
  accessToken: string,
): Promise<TaEffectivenessSectionRoster> {
  return apiGet<TaEffectivenessSectionRoster>(
    taEffectivenessRosterPath(sectionId),
    accessToken,
  );
}

export function getTaEffectivenessStudentDetail(
  sectionId: string,
  studentUserId: string,
  accessToken: string,
): Promise<TaEffectivenessStudentDetail> {
  return apiGet<TaEffectivenessStudentDetail>(
    `/professor/sections/${encodeURIComponent(sectionId)}/students/${encodeURIComponent(studentUserId)}/ta-effectiveness`,
    accessToken,
  );
}

export function getTaEffectivenessSessionTurns(
  sectionId: string,
  sessionId: string,
  evaluationRunId: string,
  accessToken: string,
): Promise<TaEffectivenessSessionTurns> {
  const params = new URLSearchParams();
  params.set("evaluation_run_id", evaluationRunId);
  return apiGet<TaEffectivenessSessionTurns>(
    `/professor/sections/${encodeURIComponent(sectionId)}/ta-effectiveness/sessions/${encodeURIComponent(sessionId)}/turns?${params.toString()}`,
    accessToken,
  );
}

export function launchTaEffectivenessRefresh(
  sectionId: string,
  accessToken: string,
  payload: TaEffectivenessRefreshPayload = {},
): Promise<EvaluationRunSummary> {
  return apiPost<TaEffectivenessRefreshPayload, EvaluationRunSummary>(
    `${taEffectivenessRosterPath(sectionId)}/refresh`,
    payload,
    accessToken,
  );
}
