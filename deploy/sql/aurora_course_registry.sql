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

INSERT INTO courses (course_id, course_source, collection_name, display_name, is_active)
VALUES
  ('mit13', 'mit13', 'mit13_course', 'MIT 6.0013', TRUE),
  ('mit14', 'mit14', 'mit14_course', 'MIT 6.0014', TRUE),
  ('cs50', 'cs50', 'cs50_course', 'Harvard CS50', TRUE)
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
