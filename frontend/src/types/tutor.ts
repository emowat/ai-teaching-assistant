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
  request_id?: string;
  turn_id?: string;
  section_id?: string;
}

export interface TutorResponse {
  answer: string;
  citations: TutorCitation[];
  guardrail_status?: string;
  session_id?: string;
  request_id?: string;
  turn_id?: string;
  turn_index?: number;
}
