import type { AppView } from "../types/navigation";

export type AppRole = "admin" | "professor" | "student";

/** Views each role may switch to (includes their primary dashboard). */
const ROLE_VIEWS: Record<AppRole, AppView[]> = {
  admin: ["admin", "professor", "student"],
  professor: ["professor", "student"],
  student: ["student"],
};

const VIEW_LABELS: Record<AppView, string> = {
  landing: "Home",
  admin: "Admin",
  professor: "Professor",
  student: "Student",
};

export function getAllowedViews(role: string | null): AppView[] {
  if (role === "admin" || role === "professor" || role === "student") {
    return ROLE_VIEWS[role];
  }
  return [];
}

export function canAccessView(role: string | null, view: AppView): boolean {
  if (view === "landing") return true;
  return getAllowedViews(role).includes(view);
}

export function getViewLabel(view: AppView): string {
  return VIEW_LABELS[view];
}

/** Default landing view after login (highest assigned role). */
export function getDefaultView(role: string | null): AppView {
  const allowed = getAllowedViews(role);
  return allowed[0] ?? "landing";
}
