const ADMIN_API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8001";

export type AdminCourseSource = "mit13" | "mit14" | "cs50";

export interface AdminCourse {
  course_id: string;
  display_name: string;
  course_source: AdminCourseSource;
  collection_name: string;
  is_active: boolean;
  has_ingestion_history: boolean;
  aliases: string[];
  syllabus_matrix?: string;
  style_guide?: string;
  created_at: string;
  updated_at: string;
}

export interface AdminCourseCreatePayload {
  course_id: string;
  display_name: string;
  course_source: AdminCourseSource;
  collection_name: string;
  is_active?: boolean;
  aliases?: string[];
  syllabus_matrix?: string;
  style_guide?: string;
}

export interface AdminCourseUpdatePayload {
  display_name?: string;
  course_source?: AdminCourseSource;
  collection_name?: string;
  is_active?: boolean;
  syllabus_matrix?: string;
  style_guide?: string;
}

export interface AdminCourseAliasCreatePayload {
  aliases: string[];
}

async function adminFetch<T>(
  path: string,
  accessToken: string,
  init?: RequestInit
): Promise<T> {
  const response = await fetch(`${ADMIN_API_BASE_URL}${path}`, {
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

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

function coursePath(courseId: string): string {
  return `/admin/courses/${encodeURIComponent(courseId)}`;
}

export function listAdminCourses(accessToken: string): Promise<AdminCourse[]> {
  return adminFetch<AdminCourse[]>("/admin/courses", accessToken);
}

export function getAdminCourse(
  courseId: string,
  accessToken: string
): Promise<AdminCourse> {
  return adminFetch<AdminCourse>(coursePath(courseId), accessToken);
}

export function createAdminCourse(
  accessToken: string,
  payload: AdminCourseCreatePayload
): Promise<AdminCourse> {
  return adminFetch<AdminCourse>("/admin/courses", accessToken, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateAdminCourse(
  courseId: string,
  accessToken: string,
  payload: AdminCourseUpdatePayload
): Promise<AdminCourse> {
  return adminFetch<AdminCourse>(coursePath(courseId), accessToken, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function addAdminCourseAliases(
  courseId: string,
  accessToken: string,
  payload: AdminCourseAliasCreatePayload
): Promise<AdminCourse> {
  return adminFetch<AdminCourse>(`${coursePath(courseId)}/aliases`, accessToken, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function removeAdminCourseAlias(
  courseId: string,
  alias: string,
  accessToken: string
): Promise<AdminCourse> {
  return adminFetch<AdminCourse>(
    `${coursePath(courseId)}/aliases/${encodeURIComponent(alias)}`,
    accessToken,
    {
      method: "DELETE",
    }
  );
}
