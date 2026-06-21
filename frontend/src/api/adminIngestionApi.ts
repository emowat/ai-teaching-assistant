const ADMIN_API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8001";

export type AdminIngestionJobKind = "parse" | "chunk-index";
export type AdminIngestionJobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "launch_failed";

export interface AdminCourseDocument {
  key: string;
  file_name: string;
  size_bytes: number;
  last_modified: string;
  etag?: string | null;
}

export interface AdminCourseDocumentListResponse {
  course_id: string;
  bucket: string;
  upload_prefix: string;
  parsed_prefix: string;
  prepared_prefix: string;
  documents: AdminCourseDocument[];
}

export interface AdminCourseDocumentUploadRequest {
  file_name: string;
  content_type?: string | null;
}

export interface AdminCourseDocumentUploadResponse {
  course_id: string;
  bucket: string;
  key: string;
  upload_prefix: string;
  parsed_prefix: string;
  prepared_prefix: string;
  upload_url: string;
  upload_method: string;
  expires_in_seconds: number;
  required_headers: Record<string, string>;
}

export interface AdminCourseDocumentDeleteResponse {
  course_id: string;
  bucket: string;
  key: string;
  deleted: boolean;
}

export interface AdminCourseCorpusVersion {
  course_corpus_version_id: string;
  course_id: string;
  collection_name: string;
  source_bucket: string;
  source_prefix: string;
  parsed_prefix?: string | null;
  prepared_prefix?: string | null;
  status: string;
  active: boolean;
  recreate_collection: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface AdminIngestionJobResponse {
  job_id: string;
  course_id: string;
  job_kind: AdminIngestionJobKind;
  status: AdminIngestionJobStatus;
  message: string;
  registered: boolean;
  course_corpus_version_id?: string | null;
  ecs_cluster: string;
  ecs_task_definition: string;
  ecs_container_name: string;
  ecs_task_arn?: string | null;
  collection_name?: string | null;
  bucket: string;
  input_prefix: string;
  output_prefix?: string | null;
  prepared_output_prefix?: string | null;
  request_payload: Record<string, string | number | boolean | null>;
  ecs_response: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface AdminIngestionJobLaunchRequest {
  course_id: string;
  job_kind: AdminIngestionJobKind;
  bucket: string;
  input_prefix: string;
  output_prefix?: string | null;
  prepared_output_prefix?: string | null;
  collection_name?: string | null;
  recreate_collection?: boolean;
}

interface AdminFetchOptions extends RequestInit {
  omitJsonContentType?: boolean;
}

async function adminFetch<T>(
  path: string,
  accessToken: string,
  init?: AdminFetchOptions
): Promise<T> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${accessToken}`,
    ...(init?.headers as Record<string, string> | undefined),
  };

  if (!init?.omitJsonContentType) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${ADMIN_API_BASE_URL}${path}`, {
    ...init,
    headers,
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

function withQuery(
  path: string,
  query: Record<string, string | number | undefined | null>
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

export function listAdminCourseDocuments(
  courseId: string,
  accessToken: string
): Promise<AdminCourseDocumentListResponse> {
  return adminFetch<AdminCourseDocumentListResponse>(
    `${coursePath(courseId)}/documents`,
    accessToken
  );
}

export function createAdminCourseDocumentUploadUrl(
  courseId: string,
  accessToken: string,
  payload: AdminCourseDocumentUploadRequest
): Promise<AdminCourseDocumentUploadResponse> {
  return adminFetch<AdminCourseDocumentUploadResponse>(
    `${coursePath(courseId)}/documents/upload-url`,
    accessToken,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export function deleteAdminCourseDocument(
  courseId: string,
  accessToken: string,
  key: string
): Promise<AdminCourseDocumentDeleteResponse> {
  return adminFetch<AdminCourseDocumentDeleteResponse>(
    withQuery(`${coursePath(courseId)}/documents`, { key }),
    accessToken,
    {
      method: "DELETE",
    }
  );
}

export function listAdminCourseCorpusVersions(
  courseId: string,
  accessToken: string,
  limit = 25
): Promise<AdminCourseCorpusVersion[]> {
  return adminFetch<AdminCourseCorpusVersion[]>(
    withQuery(`${coursePath(courseId)}/corpus-versions`, { limit }),
    accessToken
  );
}

export function listAdminIngestionJobs(
  accessToken: string,
  options?: { courseId?: string; limit?: number }
): Promise<AdminIngestionJobResponse[]> {
  return adminFetch<AdminIngestionJobResponse[]>(
    withQuery("/admin/ingestion/jobs", {
      course_id: options?.courseId,
      limit: options?.limit ?? 25,
    }),
    accessToken
  );
}

export function launchAdminIngestionJob(
  accessToken: string,
  payload: AdminIngestionJobLaunchRequest
): Promise<AdminIngestionJobResponse> {
  return adminFetch<AdminIngestionJobResponse>("/admin/ingestion/launch", accessToken, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function uploadAdminCourseDocument(
  target: AdminCourseDocumentUploadResponse,
  file: File
): Promise<void> {
  const response = await fetch(target.upload_url, {
    method: target.upload_method,
    headers: target.required_headers,
    body: file,
  });

  if (!response.ok) {
    throw new Error(`Upload failed with status ${response.status}.`);
  }
}
