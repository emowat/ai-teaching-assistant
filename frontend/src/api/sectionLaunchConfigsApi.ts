import { apiGet, apiPut } from "./client.ts";

export interface SectionLaunchConfig {
  launch_id: string;
  label: string;
  repo_url: string;
  template_url: string;
  default_branch: string;
  enabled: boolean;
  sort_order: number;
}

export function sectionLaunchConfigPath(sectionId: string): string {
  return `/professor/sections/${encodeURIComponent(sectionId)}/launch-configs`;
}

export function listProfessorSectionLaunchConfigs(
  sectionId: string,
  accessToken: string,
): Promise<SectionLaunchConfig[]> {
  return apiGet<SectionLaunchConfig[]>(sectionLaunchConfigPath(sectionId), accessToken);
}

export function replaceProfessorSectionLaunchConfigs(
  sectionId: string,
  accessToken: string,
  payload: SectionLaunchConfig[],
): Promise<SectionLaunchConfig[]> {
  return apiPut<SectionLaunchConfig[], SectionLaunchConfig[]>(
    sectionLaunchConfigPath(sectionId),
    payload,
    accessToken,
  );
}
