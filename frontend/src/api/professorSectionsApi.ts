import { apiGet, apiPost } from "./client.ts";
import type {
  SectionMembershipRole,
  SectionMembershipStatus,
} from "./adminUsersApi";

export interface ProfessorSectionSummary {
  section_id: string;
  course_id: string;
  course_display_name: string;
  display_name: string;
  term: string;
  is_active: boolean;
  professor_count: number;
  ta_count: number;
  student_count: number;
  created_at: string;
  updated_at: string;
}

export interface ProfessorSectionStudent {
  user_id: string;
  cognito_sub: string | null;
  email: string;
  display_name: string;
  membership_status: SectionMembershipStatus;
  role_in_section: SectionMembershipRole;
  session_count: number;
  last_session_at: string;
}

export interface ProfessorSectionAnalyticsPoint {
  day: string;
  sessions: number;
  active_students: number;
}

export interface AnalyticsCognitiveProgressionPoint {
  x: string;
  stage_name: string;
  count: number;
}

export interface AnalyticsPedagogicalActionPoint {
  stage_name: string;
  scaffold_name: string;
  count: number;
}

export interface AnalyticsFrustrationPoint {
  week: string;
  frustration: number;
  queries: number;
}

export interface AnalyticsTimeUtilizationPoint {
  assignment: string;
  chat: number;
  editor: number;
  terminal: number;
}

export interface AnalyticsPasteIncident {
  created_at: string;
  session_id: string;
  pasted_char_count: number;
}

export interface ProfessorSectionAnalytics {
  section: ProfessorSectionSummary;
  sessions_last_7_days: number;
  active_students_last_7_days: number;
  weekly_activity: ProfessorSectionAnalyticsPoint[];
  top_students: ProfessorSectionStudent[];
  cognitive_progression: AnalyticsCognitiveProgressionPoint[];
  pedagogical_actions: AnalyticsPedagogicalActionPoint[];
  frustration_by_week: AnalyticsFrustrationPoint[];
  time_utilization: AnalyticsTimeUtilizationPoint[];
  generated_at: string;
}

export interface ProfessorSectionStudentAnalyticsPoint {
  day: string;
  sessions: number;
  turns: number;
}

export interface ProfessorSectionStudentAnalytics {
  section: ProfessorSectionSummary;
  student: ProfessorSectionStudent;
  total_sessions: number;
  total_turns: number;
  sessions_last_7_days: number;
  turns_last_7_days: number;
  positive_feedback_count: number;
  negative_feedback_count: number;
  last_activity_at: string;
  weekly_activity: ProfessorSectionStudentAnalyticsPoint[];
  cognitive_progression: AnalyticsCognitiveProgressionPoint[];
  pedagogical_actions: AnalyticsPedagogicalActionPoint[];
  frustration_by_week: AnalyticsFrustrationPoint[];
  time_utilization: AnalyticsTimeUtilizationPoint[];
  external_paste_count: number;
  paste_incidents: AnalyticsPasteIncident[];
  generated_at: string;
}

export interface ProfessorStudentFeedbackEntry {
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

export interface ProfessorStudentFeedbackResponse {
  feedback: ProfessorStudentFeedbackEntry[];
}

export interface ProfessorSectionStudentInvitePayload {
  email: string;
  display_name?: string;
}

export function professorSectionStudentsPath(sectionId: string): string {
  return `/professor/sections/${encodeURIComponent(sectionId)}/students`;
}

export function professorSectionAnalyticsPath(
  sectionId: string,
  tz = "America/Los_Angeles",
): string {
  return `/professor/sections/${encodeURIComponent(sectionId)}/analytics?tz=${encodeURIComponent(tz)}`;
}

export function listProfessorSections(
  accessToken: string,
): Promise<ProfessorSectionSummary[]> {
  return apiGet<ProfessorSectionSummary[]>("/professor/sections", accessToken);
}

export function listProfessorSectionStudents(
  sectionId: string,
  accessToken: string,
): Promise<ProfessorSectionStudent[]> {
  return apiGet<ProfessorSectionStudent[]>(
    professorSectionStudentsPath(sectionId),
    accessToken,
  );
}

export function inviteProfessorSectionStudent(
  sectionId: string,
  accessToken: string,
  payload: ProfessorSectionStudentInvitePayload,
): Promise<ProfessorSectionStudent[]> {
  return apiPost<
    ProfessorSectionStudentInvitePayload,
    ProfessorSectionStudent[]
  >(professorSectionStudentsPath(sectionId), payload, accessToken);
}

export function getProfessorSectionAnalytics(
  sectionId: string,
  accessToken: string,
  tz = "America/Los_Angeles",
): Promise<ProfessorSectionAnalytics> {
  return apiGet<ProfessorSectionAnalytics>(
    professorSectionAnalyticsPath(sectionId, tz),
    accessToken,
  );
}

export function professorSectionStudentAnalyticsPath(
  sectionId: string,
  studentUserId: string,
  tz = "America/Los_Angeles",
): string {
  return `/professor/sections/${encodeURIComponent(sectionId)}/students/${encodeURIComponent(studentUserId)}/analytics?tz=${encodeURIComponent(tz)}`;
}

export function getProfessorSectionStudentAnalytics(
  sectionId: string,
  studentUserId: string,
  accessToken: string,
  tz: string = Intl.DateTimeFormat().resolvedOptions().timeZone,
): Promise<ProfessorSectionStudentAnalytics> {
  const params = new URLSearchParams();
  if (tz) params.append("tz", tz);
  return apiGet<ProfessorSectionStudentAnalytics>(
    `/professor/sections/${encodeURIComponent(sectionId)}/students/${encodeURIComponent(studentUserId)}/analytics?${params.toString()}`,
    accessToken,
  );
}

export function getProfessorSectionStudentFeedback(
  sectionId: string,
  studentUserId: string,
  accessToken: string,
  limit: number = 50,
): Promise<ProfessorStudentFeedbackResponse> {
  const params = new URLSearchParams();
  params.append("limit", limit.toString());
  return apiGet<ProfessorStudentFeedbackResponse>(
    `/professor/sections/${encodeURIComponent(sectionId)}/students/${encodeURIComponent(studentUserId)}/feedback?${params.toString()}`,
    accessToken,
  );
}
