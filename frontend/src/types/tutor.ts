export interface TutorCitation {
  title: string;
  source?: string;
  url?: string;
  chunk_id?: string;
}

export interface TutorRequest {
  message: string;
  course_id: string;
  session_id?: string;
}

export interface TutorResponse {
  answer: string;
  citations: TutorCitation[];
  guardrail_status?: string;
}
