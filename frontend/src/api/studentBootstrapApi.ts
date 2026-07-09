import { apiGet } from "./client.ts";
import type { SectionLaunchConfig } from "./sectionLaunchConfigsApi.ts";

export interface StudentBootstrapUser {
  app_user_id: string;
  cognito_sub: string | null;
  email: string;
  display_name: string;
  primary_role: "admin" | "professor" | "student";
  status: "invited" | "active" | "disabled";
}

export interface StudentBootstrapSection {
  section_id: string;
  course_id: string;
  course_display_name: string;
  display_name: string;
  term: string;
  is_active: boolean;
  membership_status: "invited" | "active" | "dropped" | "disabled";
  launch_configs: SectionLaunchConfig[];
}

export interface StudentBootstrapEndpoints {
  chat: string;
  telemetry: string;
  feedback: string;
}

export interface StudentBootstrapResponse {
  user: StudentBootstrapUser;
  sections: StudentBootstrapSection[];
  default_section_id: string | null;
  endpoints: StudentBootstrapEndpoints;
}

export const studentBootstrapPath = "/api/student/bootstrap";

export function getStudentBootstrap(accessToken: string): Promise<StudentBootstrapResponse> {
  return apiGet<StudentBootstrapResponse>(studentBootstrapPath, accessToken);
}
