-- Aurora course registry bootstrap for the codingrabbit capstone.
-- Keep this file versioned in Git so schema changes are reviewable.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

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

CREATE TABLE IF NOT EXISTS course_corpus_versions (
  course_corpus_version_id text PRIMARY KEY,
  course_id text NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
  collection_name text NOT NULL,
  source_bucket text NOT NULL,
  source_prefix text NOT NULL,
  parsed_prefix text,
  prepared_prefix text,
  status text NOT NULL DEFAULT 'queued',
  active boolean NOT NULL DEFAULT FALSE,
  recreate_collection boolean NOT NULL DEFAULT FALSE,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  completed_at timestamptz
);

CREATE TABLE IF NOT EXISTS users (
  user_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cognito_sub text UNIQUE,
  email text UNIQUE NOT NULL,
  display_name text NOT NULL DEFAULT '',
  primary_role text NOT NULL CHECK (primary_role IN ('admin', 'professor', 'student')),
  status text NOT NULL DEFAULT 'invited' CHECK (status IN ('invited', 'active', 'disabled')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sections (
  section_id text PRIMARY KEY,
  course_id text NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
  display_name text NOT NULL,
  term text NOT NULL DEFAULT '',
  is_active boolean NOT NULL DEFAULT TRUE,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS section_memberships (
  section_id text NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  role_in_section text NOT NULL CHECK (role_in_section IN ('professor', 'ta', 'student')),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('invited', 'active', 'dropped', 'disabled')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (section_id, user_id)
);

CREATE TABLE IF NOT EXISTS section_launch_configs (
  section_id text NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
  launch_id text NOT NULL,
  label text NOT NULL,
  repo_url text NOT NULL DEFAULT '',
  template_url text NOT NULL DEFAULT '',
  default_branch text NOT NULL DEFAULT 'main',
  enabled boolean NOT NULL DEFAULT FALSE,
  sort_order integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (section_id, launch_id)
);

CREATE INDEX IF NOT EXISTS users_email_idx
  ON users (email);

CREATE INDEX IF NOT EXISTS users_cognito_sub_idx
  ON users (cognito_sub);

CREATE INDEX IF NOT EXISTS sections_course_id_is_active_idx
  ON sections (course_id, is_active);

CREATE INDEX IF NOT EXISTS section_memberships_user_id_status_idx
  ON section_memberships (user_id, status);

CREATE INDEX IF NOT EXISTS section_memberships_section_id_role_status_idx
  ON section_memberships (section_id, role_in_section, status);

CREATE INDEX IF NOT EXISTS section_launch_configs_section_id_enabled_sort_idx
  ON section_launch_configs (section_id, enabled, sort_order, launch_id);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
  job_id text PRIMARY KEY,
  course_id text NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
  course_corpus_version_id text REFERENCES course_corpus_versions(course_corpus_version_id) ON DELETE SET NULL,
  job_kind text NOT NULL,
  status text NOT NULL DEFAULT 'queued',
  message text NOT NULL DEFAULT '',
  bucket text NOT NULL,
  input_prefix text NOT NULL,
  output_prefix text,
  prepared_output_prefix text,
  collection_name text NOT NULL,
  recreate_collection boolean NOT NULL DEFAULT FALSE,
  ecs_cluster text NOT NULL DEFAULT '',
  ecs_task_definition text NOT NULL DEFAULT '',
  ecs_container_name text NOT NULL DEFAULT '',
  ecs_task_arn text,
  request_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  ecs_response jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  completed_at timestamptz
);

CREATE TABLE IF NOT EXISTS tutor_sessions (
  session_id text PRIMARY KEY,
  user_sub text,
  app_user_id uuid,
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
  app_user_id uuid,
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

CREATE TABLE IF NOT EXISTS tutor_turn_snapshots (
  turn_id text PRIMARY KEY REFERENCES tutor_turns(turn_id) ON DELETE CASCADE,
  session_id text NOT NULL REFERENCES tutor_sessions(session_id) ON DELETE CASCADE,
  request_id text NOT NULL,
  turn_index integer NOT NULL,
  user_sub text,
  app_user_id uuid,
  course_id text NOT NULL DEFAULT '',
  course_source text NOT NULL DEFAULT '',
  section_id text,
  schema_version text NOT NULL DEFAULT 'v1',
  snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS telemetry_events (
  event_id bigserial PRIMARY KEY,
  request_id text NOT NULL,
  session_id text NOT NULL REFERENCES tutor_sessions(session_id) ON DELETE CASCADE,
  turn_id text NOT NULL REFERENCES tutor_turns(turn_id) ON DELETE CASCADE,
  turn_index integer NOT NULL,
  user_sub text,
  app_user_id uuid,
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

ALTER TABLE tutor_sessions
  ADD COLUMN IF NOT EXISTS app_user_id uuid;

ALTER TABLE tutor_turns
  ADD COLUMN IF NOT EXISTS app_user_id uuid;

ALTER TABLE tutor_turn_snapshots
  ADD COLUMN IF NOT EXISTS app_user_id uuid;

ALTER TABLE telemetry_events
  ADD COLUMN IF NOT EXISTS app_user_id uuid;

INSERT INTO courses (course_id, course_source, collection_name, display_name, is_active)
VALUES
  ('mit13', 'mit13', 'course_knowledge', 'MIT 6.0013', TRUE),
  ('mit14', 'mit14', 'mit14_course_BAAI_bge_large_en_v1_5', 'MIT 6.0014', TRUE),
  ('cs50', 'cs50', 'harvard_cs50_BAAI_bge_large_en_v1_5', 'Harvard CS50', TRUE)
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
