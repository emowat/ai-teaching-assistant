import { apiGet, apiPatch, apiPost } from "./client";
import type {
  SectionMembershipRole,
  SectionMembershipStatus,
  SectionMembershipSummary,
} from "./adminUsersApi";

export interface AdminSection {
  section_id: string;
  course_id: string;
  course_display_name: string;
  display_name: string;
  term: string;
  is_active: boolean;
  professor_count: number;
  ta_count: number;
  student_count: number;
  memberships: SectionMembershipSummary[];
  created_at: string;
  updated_at: string;
}

export interface AdminSectionCreatePayload {
  section_id: string;
  course_id: string;
  display_name: string;
  term?: string;
  is_active?: boolean;
}

export interface AdminSectionUpdatePayload {
  display_name?: string;
  term?: string;
  is_active?: boolean;
}

export interface AdminSectionMembershipCreatePayload {
  user_id: string;
  role_in_section: SectionMembershipRole;
  status?: SectionMembershipStatus;
}

export interface AdminSectionMembershipUpdatePayload {
  role_in_section?: SectionMembershipRole;
  status?: SectionMembershipStatus;
}

function sectionPath(sectionId: string): string {
  return `/admin/sections/${encodeURIComponent(sectionId)}`;
}

export function listAdminSections(accessToken: string): Promise<AdminSection[]> {
  return apiGet<AdminSection[]>("/admin/sections", accessToken);
}

export function createAdminSection(
  accessToken: string,
  payload: AdminSectionCreatePayload
): Promise<AdminSection> {
  return apiPost<AdminSectionCreatePayload, AdminSection>("/admin/sections", payload, accessToken);
}

export function updateAdminSection(
  sectionId: string,
  accessToken: string,
  payload: AdminSectionUpdatePayload
): Promise<AdminSection> {
  return apiPatch<AdminSectionUpdatePayload, AdminSection>(sectionPath(sectionId), payload, accessToken);
}

export function createAdminSectionMembership(
  sectionId: string,
  accessToken: string,
  payload: AdminSectionMembershipCreatePayload
): Promise<AdminSection> {
  return apiPost<AdminSectionMembershipCreatePayload, AdminSection>(
    `${sectionPath(sectionId)}/memberships`,
    payload,
    accessToken
  );
}

export function updateAdminSectionMembership(
  sectionId: string,
  userId: string,
  accessToken: string,
  payload: AdminSectionMembershipUpdatePayload
): Promise<AdminSection> {
  return apiPatch<AdminSectionMembershipUpdatePayload, AdminSection>(
    `${sectionPath(sectionId)}/memberships/${encodeURIComponent(userId)}`,
    payload,
    accessToken
  );
}
