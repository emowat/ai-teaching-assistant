import { apiDelete, apiGet, apiPatch, apiPost } from "./client.ts";

export type TeachingPlanStatus = "draft" | "published" | "archived";
export type SectionWeekVisibilityStatus = "hidden" | "open" | "closed";
export type WeekReferenceType =
  | "course_doc"
  | "external_link"
  | "assignment"
  | "reading"
  | "tooling";

export interface ProfessorTeachingPlanWeekReference {
  reference_id: string;
  week_id: string;
  section_id: string;
  title: string;
  reference_type: WeekReferenceType;
  url: string;
  course_document_key: string;
  notes: string;
  enabled: boolean;
  include_in_prompt: boolean;
  include_in_retrieval: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface ProfessorTeachingPlanWeek {
  week_id: string;
  teaching_plan_id: string;
  week_number: number;
  title: string;
  topic: string;
  start_date: string | null;
  end_date: string | null;
  learning_objectives: string[];
  instructional_guidance: string;
  status: TeachingPlanStatus;
  student_visibility_status?: SectionWeekVisibilityStatus;
  available_from?: string | null;
  available_until?: string | null;
  references: ProfessorTeachingPlanWeekReference[];
  created_at: string;
  updated_at: string;
}

export interface ProfessorTeachingPlan {
  teaching_plan_id: string | null;
  section_id: string;
  version: number;
  status: TeachingPlanStatus;
  title: string;
  summary: string;
  created_by_user_id: string | null;
  published_by_user_id: string | null;
  published_at: string | null;
  weeks: ProfessorTeachingPlanWeek[];
  created_at: string;
  updated_at: string;
}

export interface ProfessorTeachingPlanUpdatePayload {
  title?: string;
  summary?: string;
}

export interface ProfessorTeachingPlanWeekCreatePayload {
  week_number: number;
  title?: string;
  topic?: string;
  start_date?: string | null;
  end_date?: string | null;
  learning_objectives?: string[];
  instructional_guidance?: string;
  status?: TeachingPlanStatus;
  student_visibility_status?: SectionWeekVisibilityStatus;
  available_from?: string | null;
  available_until?: string | null;
}

export interface ProfessorTeachingPlanWeekUpdatePayload {
  week_number?: number;
  title?: string;
  topic?: string;
  start_date?: string | null;
  end_date?: string | null;
  learning_objectives?: string[];
  instructional_guidance?: string;
  status?: TeachingPlanStatus;
  student_visibility_status?: SectionWeekVisibilityStatus;
  available_from?: string | null;
  available_until?: string | null;
}

export interface ProfessorTeachingPlanWeekReferenceCreatePayload {
  title: string;
  reference_type?: WeekReferenceType;
  url?: string;
  course_document_key?: string;
  notes?: string;
  enabled?: boolean;
  include_in_prompt?: boolean;
  include_in_retrieval?: boolean;
  sort_order?: number;
}

export interface ProfessorTeachingPlanWeekReferenceUpdatePayload {
  title?: string;
  reference_type?: WeekReferenceType;
  url?: string;
  course_document_key?: string;
  notes?: string;
  enabled?: boolean;
  include_in_prompt?: boolean;
  include_in_retrieval?: boolean;
  sort_order?: number;
}

function teachingPlanPath(sectionId: string): string {
  return `/professor/sections/${encodeURIComponent(sectionId)}/teaching-plan`;
}

function teachingPlanWeekPath(sectionId: string, weekId: string): string {
  return `${teachingPlanPath(sectionId)}/weeks/${encodeURIComponent(weekId)}`;
}

function teachingPlanWeekReferencesPath(sectionId: string, weekId: string): string {
  return `${teachingPlanWeekPath(sectionId, weekId)}/references`;
}

function teachingPlanWeekReferencePath(
  sectionId: string,
  weekId: string,
  referenceId: string,
): string {
  return `${teachingPlanWeekReferencesPath(sectionId, weekId)}/${encodeURIComponent(referenceId)}`;
}

export function getProfessorTeachingPlan(
  sectionId: string,
  accessToken: string,
): Promise<ProfessorTeachingPlan> {
  return apiGet<ProfessorTeachingPlan>(teachingPlanPath(sectionId), accessToken);
}

export function saveProfessorTeachingPlan(
  sectionId: string,
  accessToken: string,
  payload: ProfessorTeachingPlanUpdatePayload,
): Promise<ProfessorTeachingPlan> {
  return apiPost<ProfessorTeachingPlanUpdatePayload, ProfessorTeachingPlan>(
    teachingPlanPath(sectionId),
    payload,
    accessToken,
  );
}

export function publishProfessorTeachingPlan(
  sectionId: string,
  accessToken: string,
): Promise<ProfessorTeachingPlan> {
  return apiPost<null, ProfessorTeachingPlan>(
    `${teachingPlanPath(sectionId)}/publish`,
    null,
    accessToken,
  );
}

export function archiveProfessorTeachingPlan(
  sectionId: string,
  accessToken: string,
): Promise<ProfessorTeachingPlan> {
  return apiPost<null, ProfessorTeachingPlan>(
    `${teachingPlanPath(sectionId)}/archive`,
    null,
    accessToken,
  );
}

export function createProfessorTeachingPlanWeek(
  sectionId: string,
  accessToken: string,
  payload: ProfessorTeachingPlanWeekCreatePayload,
): Promise<ProfessorTeachingPlan> {
  return apiPost<ProfessorTeachingPlanWeekCreatePayload, ProfessorTeachingPlan>(
    `${teachingPlanPath(sectionId)}/weeks`,
    payload,
    accessToken,
  );
}

export function updateProfessorTeachingPlanWeek(
  sectionId: string,
  weekId: string,
  accessToken: string,
  payload: ProfessorTeachingPlanWeekUpdatePayload,
): Promise<ProfessorTeachingPlan> {
  return apiPatch<ProfessorTeachingPlanWeekUpdatePayload, ProfessorTeachingPlan>(
    teachingPlanWeekPath(sectionId, weekId),
    payload,
    accessToken,
  );
}

export function deleteProfessorTeachingPlanWeek(
  sectionId: string,
  weekId: string,
  accessToken: string,
): Promise<ProfessorTeachingPlan> {
  return apiDelete<ProfessorTeachingPlan>(teachingPlanWeekPath(sectionId, weekId), accessToken);
}

export function getProfessorTeachingPlanWeek(
  sectionId: string,
  weekId: string,
  accessToken: string,
): Promise<ProfessorTeachingPlanWeek> {
  return apiGet<ProfessorTeachingPlanWeek>(teachingPlanWeekPath(sectionId, weekId), accessToken);
}

export function listProfessorTeachingPlanWeekReferences(
  sectionId: string,
  weekId: string,
  accessToken: string,
): Promise<ProfessorTeachingPlanWeekReference[]> {
  return apiGet<ProfessorTeachingPlanWeekReference[]>(
    teachingPlanWeekReferencesPath(sectionId, weekId),
    accessToken,
  );
}

export function createProfessorTeachingPlanWeekReference(
  sectionId: string,
  weekId: string,
  accessToken: string,
  payload: ProfessorTeachingPlanWeekReferenceCreatePayload,
): Promise<ProfessorTeachingPlanWeek> {
  return apiPost<ProfessorTeachingPlanWeekReferenceCreatePayload, ProfessorTeachingPlanWeek>(
    teachingPlanWeekReferencesPath(sectionId, weekId),
    payload,
    accessToken,
  );
}

export function updateProfessorTeachingPlanWeekReference(
  sectionId: string,
  weekId: string,
  referenceId: string,
  accessToken: string,
  payload: ProfessorTeachingPlanWeekReferenceUpdatePayload,
): Promise<ProfessorTeachingPlanWeek> {
  return apiPatch<ProfessorTeachingPlanWeekReferenceUpdatePayload, ProfessorTeachingPlanWeek>(
    teachingPlanWeekReferencePath(sectionId, weekId, referenceId),
    payload,
    accessToken,
  );
}

export function deleteProfessorTeachingPlanWeekReference(
  sectionId: string,
  weekId: string,
  referenceId: string,
  accessToken: string,
): Promise<ProfessorTeachingPlanWeek> {
  return apiDelete<ProfessorTeachingPlanWeek>(
    teachingPlanWeekReferencePath(sectionId, weekId, referenceId),
    accessToken,
  );
}
