import type { CognitoGroup } from "../types/auth";

export function getUserGroups(profile: unknown): CognitoGroup[] {
  if (!profile || typeof profile !== "object") return [];

  const groups = (profile as Record<string, unknown>)["cognito:groups"];

  if (Array.isArray(groups)) {
    return groups.filter((g): g is CognitoGroup => typeof g === "string");
  }

  if (typeof groups === "string") {
    return [groups as CognitoGroup];
  }

  return [];
}

export function getPrimaryRole(groups: CognitoGroup[]): string | null {
  if (groups.includes("Admins")) return "admin";
  if (groups.includes("Professors")) return "professor";
  if (groups.includes("Students")) return "student";
  return null;
}
