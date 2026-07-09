import { apiGet } from "./client.ts";
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

export function professorSectionStudentsPath(sectionId: string): string {
  return `/professor/sections/${encodeURIComponent(sectionId)}/students`;
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
