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

export interface ProfessorSectionAnalytics {
  section: ProfessorSectionSummary;
  sessions_last_7_days: number;
  active_students_last_7_days: number;
  weekly_activity: ProfessorSectionAnalyticsPoint[];
  top_students: ProfessorSectionStudent[];
  generated_at: string;
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
  accessToken: string
): Promise<ProfessorSectionSummary[]> {
  return apiGet<ProfessorSectionSummary[]>("/professor/sections", accessToken);
}

export function listProfessorSectionStudents(
  sectionId: string,
  accessToken: string
): Promise<ProfessorSectionStudent[]> {
  return apiGet<ProfessorSectionStudent[]>(professorSectionStudentsPath(sectionId), accessToken);
}

export function inviteProfessorSectionStudent(
  sectionId: string,
  accessToken: string,
  payload: ProfessorSectionStudentInvitePayload,
): Promise<ProfessorSectionStudent[]> {
  return apiPost<ProfessorSectionStudentInvitePayload, ProfessorSectionStudent[]>(
    professorSectionStudentsPath(sectionId),
    payload,
    accessToken,
  );
}

export function getProfessorSectionAnalytics(
  sectionId: string,
  accessToken: string,
  tz = "America/Los_Angeles",
): Promise<ProfessorSectionAnalytics> {
  return apiGet<ProfessorSectionAnalytics>(professorSectionAnalyticsPath(sectionId, tz), accessToken);
}
