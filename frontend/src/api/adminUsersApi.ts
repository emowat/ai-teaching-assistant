import { apiGet, apiPatch, apiPost } from "./client";

export type AppPrimaryRole = "admin" | "professor" | "student";
export type UserStatus = "invited" | "active" | "disabled";
export type SectionMembershipStatus = "invited" | "active" | "dropped" | "disabled";
export type SectionMembershipRole = "professor" | "ta" | "student";

export interface SectionMembershipSummary {
  section_id: string;
  user_id?: string | null;
  section_display_name: string;
  course_id: string;
  course_display_name: string;
  role_in_section: SectionMembershipRole;
  status: SectionMembershipStatus;
  created_at: string;
  updated_at: string;
}

export interface AdminUser {
  user_id: string;
  cognito_sub: string | null;
  email: string;
  display_name: string;
  primary_role: AppPrimaryRole;
  status: UserStatus;
  section_memberships: SectionMembershipSummary[];
  created_at: string;
  updated_at: string;
}

export interface AdminUserCreatePayload {
  email: string;
  display_name: string;
  primary_role: AppPrimaryRole;
  status?: UserStatus;
}

export interface AdminUserUpdatePayload {
  display_name?: string;
  primary_role?: AppPrimaryRole;
  status?: UserStatus;
}

function userPath(userId: string): string {
  return `/admin/users/${encodeURIComponent(userId)}`;
}

export function listAdminUsers(accessToken: string): Promise<AdminUser[]> {
  return apiGet<AdminUser[]>("/admin/users", accessToken);
}

export function createAdminUser(
  accessToken: string,
  payload: AdminUserCreatePayload
): Promise<AdminUser> {
  return apiPost<AdminUserCreatePayload, AdminUser>("/admin/users", payload, accessToken);
}

export function updateAdminUser(
  userId: string,
  accessToken: string,
  payload: AdminUserUpdatePayload
): Promise<AdminUser> {
  return apiPatch<AdminUserUpdatePayload, AdminUser>(userPath(userId), payload, accessToken);
}
