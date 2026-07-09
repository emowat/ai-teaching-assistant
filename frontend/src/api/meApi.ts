import { apiGet } from "./client.ts";
import type { AppUser } from "../types/auth";

export function getMe(accessToken: string): Promise<AppUser> {
  return apiGet<AppUser>("/me", accessToken);
}
