import { API_BASE_URL } from "./client.ts";

export interface StudentDashboardStats {
  available_courses: string[];
  live_stats: {
    requests: number;
    rewards: number;
    nudges: number;
  };
  cognitive_progression: {
    x: string;
    stage_name: string;
    count: number;
  }[];
  time_utilization: {
    assignment: string;
    chat: number;
    editor: number;
    terminal: number;
  }[];
  pedagogical_actions: {
    stage_name: string;
    scaffold_name: string;
    count: number;
  }[];
  frustration_by_week: {
    week: string;
    frustration: number;
    queries: number;
  }[];
}

export async function getStudentDashboardStats(
  accessToken: string,
  courseId?: string,
  tz: string = Intl.DateTimeFormat().resolvedOptions().timeZone
): Promise<StudentDashboardStats> {
  const params = new URLSearchParams();
  if (tz) params.append("tz", tz);
  if (courseId) params.append("course_id", courseId);
  const qs = params.toString() ? `?${params.toString()}` : "";

  const response = await fetch(`${API_BASE_URL}/api/student/dashboard/stats${qs}`, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`API error ${response.status}: ${await response.text()}`);
  }

  return response.json();
}
