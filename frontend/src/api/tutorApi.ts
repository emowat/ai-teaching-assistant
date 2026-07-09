import { apiPost } from "./client.ts";
import type { TutorRequest, TutorResponse } from "../types/tutor";

export function askTutor(
  request: TutorRequest,
  accessToken: string
): Promise<TutorResponse> {
  return apiPost<TutorRequest, TutorResponse>(
    "/tutor/respond",
    request,
    accessToken
  );
}
