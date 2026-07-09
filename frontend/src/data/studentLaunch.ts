import type { SectionLaunchConfig } from "../api/sectionLaunchConfigsApi.ts";
import type { StudentBootstrapResponse } from "../api/studentBootstrapApi.ts";

export function pickDefaultSection(bootstrap: StudentBootstrapResponse): string | null {
  return bootstrap.default_section_id ?? bootstrap.sections[0]?.section_id ?? null;
}

export function pickDefaultLaunchId(sectionLaunchConfigs: SectionLaunchConfig[]): string | null {
  return (
    sectionLaunchConfigs.find((config) => config.enabled)?.launch_id ??
    sectionLaunchConfigs[0]?.launch_id ??
    null
  );
}
