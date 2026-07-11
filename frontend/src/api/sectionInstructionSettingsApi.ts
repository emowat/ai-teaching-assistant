import { apiGet, apiPatch } from "./client.ts";

export type SectionWeekResolutionMode = "manual" | "date_driven";

export type SectionWeekVisibilityStatus = "hidden" | "open" | "closed";

export interface SectionInstructionSettings {
  section_id: string;
  student_access_enabled: boolean;
  week_resolution_mode: SectionWeekResolutionMode;
  manual_current_week_number: number | null;
  teaching_plan_prompt_enabled: boolean;
  references_prompt_enabled: boolean;
  references_retrieval_enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface SectionInstructionSettingsUpdatePayload {
  student_access_enabled?: boolean;
  week_resolution_mode?: SectionWeekResolutionMode;
  manual_current_week_number?: number | null;
  teaching_plan_prompt_enabled?: boolean;
  references_prompt_enabled?: boolean;
  references_retrieval_enabled?: boolean;
}

function instructionSettingsPath(sectionId: string): string {
  return `/professor/sections/${encodeURIComponent(sectionId)}/instruction-settings`;
}

export function getProfessorSectionInstructionSettings(
  sectionId: string,
  accessToken: string,
): Promise<SectionInstructionSettings> {
  return apiGet<SectionInstructionSettings>(instructionSettingsPath(sectionId), accessToken);
}

export function updateProfessorSectionInstructionSettings(
  sectionId: string,
  accessToken: string,
  payload: SectionInstructionSettingsUpdatePayload,
): Promise<SectionInstructionSettings> {
  return apiPatch<SectionInstructionSettingsUpdatePayload, SectionInstructionSettings>(
    instructionSettingsPath(sectionId),
    payload,
    accessToken,
  );
}
