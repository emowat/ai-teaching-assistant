-- Aurora course registry bootstrap for the codingrabbit capstone.
-- Keep this file versioned in Git so schema changes are reviewable.

CREATE TABLE IF NOT EXISTS courses (
  course_id text PRIMARY KEY,
  course_source text NOT NULL,
  collection_name text NOT NULL,
  display_name text NOT NULL DEFAULT '',
  is_active boolean NOT NULL DEFAULT TRUE,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS course_aliases (
  alias text PRIMARY KEY,
  course_id text NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
  is_active boolean NOT NULL DEFAULT TRUE,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tutor_sessions (
  session_id text PRIMARY KEY,
  user_sub text,
  course_id text NOT NULL DEFAULT '',
  course_source text NOT NULL DEFAULT '',
  section_id text,
  first_request_id text,
  last_request_id text,
  turn_count integer NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'active',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tutor_turns (
  turn_id text PRIMARY KEY,
  session_id text NOT NULL REFERENCES tutor_sessions(session_id) ON DELETE CASCADE,
  request_id text NOT NULL,
  turn_index integer NOT NULL,
  user_sub text,
  course_id text NOT NULL DEFAULT '',
  course_source text NOT NULL DEFAULT '',
  section_id text,
  mode text NOT NULL DEFAULT '',
  week integer NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'started',
  model_provider text NOT NULL DEFAULT '',
  model_name text NOT NULL DEFAULT '',
  retrieval_doc_count integer NOT NULL DEFAULT 0,
  answer_chars integer NOT NULL DEFAULT 0,
  latency_ms integer,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);

CREATE TABLE IF NOT EXISTS telemetry_events (
  event_id bigserial PRIMARY KEY,
  request_id text NOT NULL,
  session_id text NOT NULL REFERENCES tutor_sessions(session_id) ON DELETE CASCADE,
  turn_id text NOT NULL REFERENCES tutor_turns(turn_id) ON DELETE CASCADE,
  turn_index integer NOT NULL,
  user_sub text,
  course_id text NOT NULL DEFAULT '',
  course_source text NOT NULL DEFAULT '',
  section_id text,
  event_type text NOT NULL,
  stage text NOT NULL,
  status text NOT NULL,
  latency_ms integer,
  model_provider text NOT NULL DEFAULT '',
  model_name text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO courses (course_id, course_source, collection_name, display_name, is_active)
VALUES
  ('mit13', 'mit13', 'course_knowledge', 'MIT 6.0013', TRUE),
  ('mit14', 'mit14', 'course_knowledge', 'MIT 6.0014', TRUE),
  ('cs50', 'cs50', 'harvard_cs50', 'Harvard CS50', TRUE)
ON CONFLICT (course_id) DO UPDATE SET
  course_source = EXCLUDED.course_source,
  collection_name = EXCLUDED.collection_name,
  display_name = EXCLUDED.display_name,
  is_active = TRUE,
  updated_at = now();

INSERT INTO course_aliases (alias, course_id, is_active)
VALUES
  ('mit', 'mit13', TRUE),
  ('mit_13', 'mit13', TRUE),
  ('mit-13', 'mit13', TRUE),
  ('mit_14', 'mit14', TRUE),
  ('mit-14', 'mit14', TRUE),
  ('harvard', 'cs50', TRUE),
  ('harvardcs50', 'cs50', TRUE),
  ('harvard-cs50', 'cs50', TRUE),
  ('cs50x', 'cs50', TRUE)
ON CONFLICT (alias) DO UPDATE SET
  course_id = EXCLUDED.course_id,
  is_active = TRUE,
  updated_at = now();
