import { apiGet } from "./client";
import type { AppUser } from "../types/auth";

export function getMe(accessToken: string): Promise<AppUser> {
  return apiGet<AppUser>("/me", accessToken);
}
