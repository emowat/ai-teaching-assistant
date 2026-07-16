import { apiGet, apiPatch, apiPost } from "./client.ts";

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

export interface AdminReportedIssue {
  issue_id: string;
  session_id: string;
  turn_index: number | null;
  student_email: string | null; // Will be redacted for admins
  section_id: string | null;
  section_name: string | null;
  professor_email: string | null;
  reason: string;
  chat_history: any[];
  status: string;
  created_at: string;
}

export interface AdminReportedIssuesResponse {
  issues: AdminReportedIssue[];
}

export interface AdminDataDeletionRequest {
  request_id: string;
  user_id: string; // Will be redacted for admins
  student_email: string; // Will be redacted for admins
  section_name: string | null;
  professor_email: string | null;
  status: string;
  created_at: string;
  scrubbed_at: string | null;
}

export interface AdminDataDeletionRequestsResponse {
  requests: AdminDataDeletionRequest[];
}

export function fetchAdminReportedIssues(accessToken: string): Promise<AdminReportedIssuesResponse> {
  return apiGet<AdminReportedIssuesResponse>(`/admin/dashboard/reported-issues`, accessToken);
}

export function resolveAdminReportedIssue(issue_id: string, accessToken: string): Promise<{ success: boolean }> {
  return apiPost<any, { success: boolean }>(`/admin/reported-issues/${issue_id}/resolve`, {}, accessToken);
}

export function fetchAdminDataDeletionRequests(accessToken: string): Promise<AdminDataDeletionRequestsResponse> {
  return apiGet<AdminDataDeletionRequestsResponse>(`/admin/dashboard/deletion-requests`, accessToken);
}

export function scrubAdminUserData(request_id: string, accessToken: string): Promise<{ success: boolean; message: string }> {
  return apiPost<any, { success: boolean; message: string }>(`/admin/consent/scrub-request/${request_id}`, {}, accessToken);
}
