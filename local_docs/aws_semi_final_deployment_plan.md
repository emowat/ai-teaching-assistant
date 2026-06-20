# AWS Semi-Final Deployment Plan

## Summary

This plan reflects the current repo state as of June 18, 2026 and updates the earlier architecture to prefer **Amazon SageMaker AI** for ML workloads because your available AWS credits apply there.

The system is split into two lanes:

1. Online lane:
   VS Code extension / web app -> `rag_eng` orchestrator -> Qdrant retrieval -> SageMaker Async Qwen -> post-LLM guardrail -> response

2. Offline lane:
   teacher uploads to S3 -> parser job -> chunk/index job -> Qdrant update -> evaluation jobs -> admin visibility

Locked decisions:

- Frontend stays on S3 + CloudFront
- `rag_eng` runs as an ECS Fargate service behind an ALB
- Aurora PostgreSQL Serverless v2 becomes the application system of record
- Main tutor model stays on SageMaker Async
- Post-LLM guardrail moves to SageMaker AI instead of ECS
- Offline parser / chunk / embed / eval jobs prefer SageMaker Processing
- Vector database remains Qdrant Cloud as an accepted external free-tier exception for the MVP
- Dynamic professor-uploaded course corpora are in scope, not just fixed MIT/Harvard content
- Raw model traces and large telemetry payloads are stored in S3
- OpenAI and Cohere remain available only as testing adapters, not as funded production dependencies
- Amazon Bedrock is the AWS-native hosted-model path for admin-managed foundation-model routes when custom SageMaker hosting is not required

## Current Implementation Status

This repository is **not end-to-end complete yet**. The plan now separates:

- what is already implemented in the repo
- what has been bootstrapped in AWS
- what still needs runtime wiring or service deployment

### Done in the repo

- explicit `course_id` routing in the online tutor path
- local course registry seam in `rag/course_registry.py`
- Aurora-backed overlay for the course registry
- Aurora bootstrap script and versioned schema in `deploy/`
- CLI smoke command for resolving a course route
- `.env.example` and `rag_eng/README.md` docs for the Aurora registry env var
- best-effort Aurora-backed session / turn / telemetry tracing hooks in `rag_eng`
- Gradio retrieval presets for experiment-backed tuning of `result_count` and rerank strategy
- Gradio guardrail diagnostics plus guardrailed non-streaming and streaming chat responses
- Bedrock provider support in the admin model configuration UI for both RAG and chat routes

### Done in AWS

- Aurora PostgreSQL cluster is created and available
- course registry schema is applied
- MIT / Harvard course registry rows are seeded
- Aurora Data API bootstrap verification succeeds

### Partial / not yet end-to-end

- backend runtime is not yet deployed in AWS with live Aurora networking
- `resolve-course` falls back locally unless the runner can reach the Aurora endpoint
- session / telemetry persistence is wired in the codebase, but the AWS-hosted
  runtime path and analytics consumers are still pending
- guardrail SageMaker endpoint is still planned, even though the local pipeline
  now runs the rule-based + CodeBERT guardrail logic in-process
- chunk / index Processing pipeline is only planned
- analytics frontend is still stubbed

### Immediate next step

The next step is **not** frontend polish. It is to make the backend runtime actually consume the Aurora registry from the AWS-hosted service path, then use that same path as the basis for sessions, telemetry, and analytics.

Recommended order after that:

1. wire the ECS backend runtime to Aurora and verify live course resolution in AWS
2. add session / telemetry persistence and the first analytics rollups
3. package the guardrail as a SageMaker endpoint
4. add the SageMaker Processing chunk/index pipeline for uploaded course content
5. backfill the frontend analytics surface once the data contracts exist

### Immediate backend slice checklist

Scope for the next implementation slice:

1. deploy or update the backend runtime so the live service runs in AWS networking
2. inject `COURSE_REGISTRY_DATABASE_URL` into the backend runtime environment
3. make sure the backend image has the `psycopg` dependency installed
4. verify the backend can reach the Aurora endpoint from inside AWS
5. confirm `rag_eng.cli resolve-course --course-id mit-14` returns the Aurora-seeded collection name, not the local fallback
6. confirm the live `/query` or `/api/chat` request path uses the same registry-backed resolution
7. stop the slice when the live backend logs no Aurora fallback warning and the resolved course collection matches the seeded database row

Acceptance criteria for this slice:

- the app runtime, not just local CLI, resolves MIT / Harvard routes through Aurora
- explicit `course_id` lookup works in the live backend service
- legacy local fallback remains available only when Aurora is unreachable
- the next slice can build sessions and telemetry on top of a verified runtime course lookup

## What Changes Because of SageMaker AI Credits

Using SageMaker AI credits does change the plan.

It does **not** change the right home for:

- the browser frontend
- the FastAPI orchestrator
- Cognito auth
- CloudFront / S3 hosting
- the accepted Qdrant Cloud free-tier exception for MVP retrieval
- the need for a relational application database

It **does** change the right home for:

- the main fine-tuned model
- the semantic guardrail model
- offline parsing / transformation / embedding / evaluation jobs

The practical adjustment is:

- keep non-ML app services on ECS / S3 / CloudFront
- move ML serving and ML-oriented batch work onto SageMaker AI wherever it fits the runtime
- keep OpenAI/Cohere only for comparison and testing, not as required production services
- treat Amazon Bedrock as the AWS-native replacement path for hosted foundation-model dependencies that should no longer rely on external APIs

## Current Codebase Facts That Drive This Plan

- `rag_eng/service.py` handles the online tutoring flow and currently performs retrieval before inference.
- `rag_eng/inference.py` already integrates with the SageMaker Async endpoint.
- `output_guardrails/combined.py` and `output_guardrails/semantic_guardrail.py` define the output guardrail logic, but they are not yet productionized as a deployed service.
- `data_ingestion/s3_teacher_file_parser.py` now exists and is S3-native, but it is parse-only.
- The parser writes normalized JSON envelopes to S3 and does not chunk, embed, or upsert to Qdrant.
- The Aurora-backed course registry bootstrap is present in `deploy/`, but the live backend runtime still needs AWS network access to use it.
- `rag_eng/indexing.py` and `rag/loader.py` still operate on repo-local / raw-data-oriented formats, not the new S3 parser envelopes.
- The retrieval stack already supports multiple collections, including MIT, guidelines, and Harvard collections.
- The online chat path still does not explicitly set course routing in a deployment-safe way.
- `QueryInput` still defaults `course_source` to Harvard, which is risky in production if the caller does not override it explicitly.
- The professor analytics UI is still stubbed in the frontend and there is no backend persistence yet for tutor sessions, per-step traces, or class-level aggregates.
- Prior repo plans already assume relational entities such as users, courses, sections, enrollments, sessions, and analytics ownership.

## Target AWS Architecture

## Frontend

- Host the React frontend in S3 behind CloudFront.
- Use one CloudFront distribution with two origins:
  - `/*` -> S3 frontend bucket
  - `/api/*`, `/admin/*`, `/health`, `/me`, `/gradio/*` -> ALB for backend
- Configure SPA fallback to `/index.html` for refreshes and deep links.
- Keep Cognito Hosted UI as the browser authentication mechanism.

## Backend Orchestrator

- Deploy `rag_eng` as a single ECS Fargate service.
- Put it behind a public ALB.
- Keep retrieval, prompt assembly, auth validation, session/telemetry ingestion, admin operations, and job launching inside this service.
- Keep pre-LLM checks inside the orchestrator:
  - auth / role validation
  - request sanity checks
  - course / week boundary checks
  - prompt / payload policy checks before GPU inference

Reason:
- SageMaker AI is not the right place to host the general-purpose FastAPI control plane.
- ECS remains the correct runtime for the orchestrator even when SageMaker AI is preferred for model and ML jobs.

## Application Data Plane

- Add **Aurora PostgreSQL Serverless v2** as the application database.
- Connect the ECS backend directly to Aurora for the MVP.
- Defer **RDS Proxy** until connection pressure or failover behavior justifies the added cost.
- Any temporary public-access changes made to test Aurora from the laptop must be
  reverted after the backend deployment is complete.

Reason:
- the project now needs queryable relationships across users, students, professors, classes, sessions, and analytics
- the frontend professor/admin surfaces need grouped reads by student, section, and course
- this is a natural relational workload, not a key-value workload
- Aurora Serverless v2 is designed for variable application workloads and can scale capacity automatically
- the MVP backend can keep connection counts low enough to skip RDS Proxy initially

Aurora is the source of truth for:
- users
- courses
- sections
- section memberships
- course corpus versions
- tutor sessions
- tutor turns
- telemetry summaries
- analytics rollups
- job registry metadata

Qdrant remains retrieval-only and is **not** the system of record for application analytics or session history.

## Main Tutor Model

- Keep the fine-tuned Qwen model on SageMaker Async.
- Continue using the current async request flow:
  - request payload written to S3
  - `InvokeEndpointAsync`
  - poll S3 for output

Reason:
- the repo is already built around this path
- SageMaker Async supports long-running inference and scale-to-zero
- this is the best match for your current deployed fine-tuned model path

Accepted tradeoff:
- first request after idle may still take minutes
- this remains the main UX risk for real student use

Testing-only provider note:
- OpenAI and Cohere routes may remain in the codebase for benchmarking, comparison, and admin testing
- they are not part of the target funded production path
- if a managed hosted model is needed beyond the fine-tuned SageMaker tutor path, prefer Amazon Bedrock over long-term dependency on external model APIs

## Post-LLM Guardrail

- Deploy the semantic guardrail model as a **separate SageMaker AI endpoint**, not as an ECS service.
- Preferred first target: **SageMaker Serverless Inference** if the packaged BERT / CodeBERT model fits the memory and latency target.
- If latency or cold starts are not acceptable, move the same container to a **small SageMaker real-time endpoint**.

Reason:
- your credits can be spent here
- the model is small enough to justify trying Serverless Inference first
- this keeps both online model-serving components inside SageMaker AI

Recommended packaging path:
- export the classifier to **ONNX Runtime**
- serve it in a small custom inference container

Recommended runtime progression:

1. first implementation:
   - SageMaker endpoint
   - existing Python model wrapper logic adapted to endpoint inference

2. production hardening:
   - ONNX Runtime container
   - benchmark latency / memory
   - decide whether Serverless Inference is sufficient or whether real-time is needed

Guardrail behavior stays the same logically:
- V1 rule-based checks
- V2 semantic classifier
- final action: `pass`, `log_only`, or `replace`

## Vector Database

- Keep Qdrant Cloud.
- Do not migrate vector storage during this deployment phase.
- Use:
  - one shared guidelines collection
  - one content collection per course corpus
- Seed the registry with the current MIT and Harvard collections.

Reason:
- current code already assumes remote Qdrant
- migrating vector storage now adds risk without improving the SageMaker AI credit story

Status note:
- Qdrant Cloud is an accepted external dependency for the MVP because the free tier is expected to be sufficient
- it is the primary non-AWS production-path exception currently tolerated in the plan

## Course Registry and Dynamic Course Routing

Dynamic uploaded courses are in scope, so the deployment must add a control-plane registry.

Recommended store:
- Aurora PostgreSQL Serverless v2

Minimum entities:
- `courses`
- `sections`
- `section_memberships`
- `course_corpus_versions`

Each course record should track:
- `course_id`
- display name
- current active corpus version
- Qdrant collection name
- teacher upload S3 prefix
- parsed JSON prefix
- prepared chunk prefix
- ingestion status
- last successful ingestion timestamp

The backend must stop relying on implicit/default course routing.

The orchestrator must derive the active course explicitly from authenticated context or request metadata before retrieval runs.

Recommended ownership model:
- `courses` = catalog-level course
- `sections` = class/cohort instance of a course
- `section_memberships` = professor/student/TA assignment
- `course_corpus_versions` = active retrieval corpus + Qdrant collection mapping for that course

This keeps class analytics and course routing in one relational model.

## Session, Telemetry, and Trace Storage

The plan must now include explicit capture of:

- VS Code extension telemetry
- web chat/session metadata
- retrieval step metadata
- main model invocation metadata
- guardrail invocation metadata
- final answer metadata

### Relational storage in Aurora

Store **queryable, joinable, low-to-medium volume** data in Aurora.

Minimum tables:

- `users`
- `courses`
- `sections`
- `section_memberships`
- `tutor_sessions`
- `tutor_turns`
- `telemetry_events`
- `pipeline_step_events`
- `course_corpus_versions`
- `analytics_student_daily`
- `analytics_section_daily`

Recommended semantics:

- `tutor_sessions`
  - one session per student working context
  - ties a student to a section/course and current assignment/week context

- `tutor_turns`
  - one user prompt / assistant answer cycle
  - stores normalized fields such as:
    - session id
    - turn index
    - mode
    - week
    - course id / section id
    - student message text
    - final assistant answer text
    - final status
    - flagged / escalated state

- `telemetry_events`
  - extension/frontend-generated coarse events
  - examples:
    - `session_started`
    - `session_resumed`
    - `session_ended`
    - `file_opened`
    - `compile_requested`
    - `compile_succeeded`
    - `compile_failed`
    - `hint_requested`
    - `hint_received`
    - `heartbeat_snapshot`

- `pipeline_step_events`
  - one row per backend pipeline stage
  - stages:
    - `request_received`
    - `retrieval`
    - `llm_inference`
    - `guardrail`
    - `answer_returned`
  - each row stores structured metadata such as:
    - start/end timestamps
    - latency
    - provider / endpoint / model
    - token counts if available
    - retrieved chunk count
    - guardrail action
    - success/failure
    - `raw_trace_s3_uri`

### Raw payloads in S3

Store **large, verbose, or privacy-sensitive trace payloads** in S3, not Aurora.

Examples:
- full prompt payloads
- full RAG context blocks
- retrieved chunk lists with content
- full guardrail evidence JSON
- code snapshots
- raw extension context blobs
- full SageMaker request/response traces

Suggested S3 layout:

- `telemetry/raw/date=YYYY-MM-DD/course_id=<course_id>/session_id=<session_id>/...`
- `traces/rag/date=...`
- `traces/llm/date=...`
- `traces/guardrail/date=...`
- `analytics/exports/date=...`

Aurora should store only the object URI and summary fields needed for filtering and grouping.

### CloudWatch role

Use CloudWatch for:
- infrastructure logs
- app logs
- SageMaker job logs
- alarmable operational metrics

Do **not** treat CloudWatch as the primary product analytics store.

### Telemetry collection policy

Do not ingest raw keystroke streams.

Extension/web telemetry should be **coarse-grained**:
- lifecycle events
- compile/test events
- help/hint events
- periodic heartbeat snapshot every 30-60 seconds
- optional “stuck” signal derived client-side or server-side

This keeps storage volume and privacy risk under control while still powering class analytics.

## Offline Ingestion Pipeline

The merged teacher parser makes the offline path a clear **two-stage pipeline**.

### Stage A: Parse uploaded teacher files

Input:
- `s3://<bucket>/teacher_uploads/<course_id>/...`

Implementation:
- run `data_ingestion/s3_teacher_file_parser.py` as a **SageMaker Processing job**

Output:
- `s3://<bucket>/parsed_json/<course_id>/...`

Supported formats currently handled by the script:
- PDF
- DOCX
- TXT
- MD
- PPTX
- HTML

Reason:
- this is data transformation work, which SageMaker Processing is designed for
- using Processing lets this batch stage consume SageMaker AI credits

### Stage B: Chunk, embed, and index parsed envelopes

Input:
- `parsed_json/<course_id>/...`

Implementation requirement:
- add a new chunk/index job that understands the parser envelope format
- run it as a **SageMaker Processing job**

Output:
- optional prepared chunk artifacts in S3
- embeddings and upserts into the target course collection in Qdrant Cloud

This stage is required because current loaders/indexers still assume repo-local course-specific formats, not the new parsed S3 envelopes.

This job should:
- create deterministic chunk IDs
- preserve provenance back to the source S3 object
- map chunks to the correct course collection
- mark the course version as ready in the course registry only after success

## Offline Evaluation

Evaluation should remain batch-oriented, not always-on.

Run evaluation as **SageMaker Processing jobs** using:
- synthetic datasets
- retrieval eval inputs
- guardrail eval inputs
- optional sampled production traces exported to S3

Write outputs to S3:
- metrics JSON
- per-run artifacts
- summaries for later admin visibility

Evaluation inputs should be able to join against:
- sampled `tutor_turns`
- `pipeline_step_events`
- raw S3 traces referenced from those rows

This keeps model evaluation and production telemetry connected.

Do not deploy a dedicated evaluation API service in this phase.

Why Processing and not Batch Transform:
- the evaluation scripts are general Python workflows, not just straight model inference
- Processing is the better fit for custom preprocessing / postprocessing / evaluation pipelines

## Job Orchestration

Trigger methods:
- admin / professor-triggered runs from backend endpoints
- EventBridge Scheduler for recurring jobs and reprocessing

Orchestration policy:
- backend launches SageMaker Processing jobs for parser / chunk-index / eval
- backend launches SageMaker endpoints for model-serving components
- backend stores job metadata and latest status in Aurora

Do not build an always-on ingestion microservice for this cut.

## Secrets, Config, and Networking

## Secrets

Use AWS Secrets Manager for:
- Qdrant API key
- Cohere key
- OpenAI key
- admin fallback token if still needed
- Aurora credentials for direct backend connection

Inject secrets into ECS tasks / services and SageMaker jobs / endpoints at runtime.

## Non-secret config

Keep non-secret deploy settings in repo config and task / job definitions:
- bucket names
- prefixes
- endpoint names
- collection naming rules
- testing-only provider enablement flags
- Bedrock model identifiers when introduced
- Aurora schema / migration settings
- polling settings
- CORS / origin settings

## Networking

- CloudFront -> public ALB for backend
- ALB -> ECS Fargate backend
- backend ECS service -> Qdrant Cloud over HTTPS
- backend ECS service -> Aurora PostgreSQL Serverless v2 directly
- backend ECS service -> SageMaker Async tutor endpoint
- backend ECS service -> SageMaker guardrail endpoint
- backend ECS service -> SageMaker Processing API for offline jobs
- SageMaker Processing jobs -> S3 + Qdrant Cloud

Keep all AWS-managed components in the same region.

## API and Interface Changes Required Before Deployment

## Online tutoring contract

The online tutoring path must become explicit about course routing.

Required behavior:
- derive `course_id` or equivalent active course context before retrieval
- map that course to the correct Qdrant collection
- remove reliance on implicit default `course_source`

## Backend admin operations

Add admin/backend control endpoints for offline jobs:

- `POST /admin/jobs/ingest`
- `POST /admin/jobs/eval`
- `GET /admin/jobs/{job_id}`

These endpoints should:
- launch SageMaker Processing jobs
- return job IDs
- expose status and latest outcome
- read status from SageMaker + Aurora + S3-backed artifacts

## Session and analytics endpoints

Add backend contracts for persistent session and analytics data.

Minimum session endpoints:

- `POST /student/sessions`
- `GET /student/sessions/{session_id}`
- `POST /student/sessions/{session_id}/messages`
- `POST /student/sessions/{session_id}/telemetry`

Minimum professor/admin analytics endpoints:

- `GET /professor/sections`
- `GET /professor/sections/{section_id}/analytics`
- `GET /professor/sections/{section_id}/students`
- `GET /professor/sections/{section_id}/flagged-sessions`
- `GET /admin/analytics/overview`

The frontend professor analytics page should eventually be backed by these reads instead of stub data.

## Guardrail service contract

Even when the guardrail is deployed on SageMaker AI, keep the internal logical contract as:

- `POST /score`

Request should include:
- draft answer
- user query
- student code
- conversation metadata
- optional course metadata

Response should include:
- `action`
- `final_answer`
- `evidence`
- `stage`
- `v2_score`

This contract is backend-internal and should be represented as a client wrapper around the SageMaker endpoint.

## Pending Detailed Design and Implementation Work

The sections below are intentionally more concrete than the architecture summary above. They define the next implementation units that must exist before the deployment plan is operationally complete.

### Pending 1: Aurora PostgreSQL schema for sessions, turns, telemetry, and analytics

Status:
- pending

Scope:
- define the application data model needed for session persistence, per-turn traceability, section/course analytics, and offline evaluation joins

Schema conventions:
- primary keys use `uuid`
- event-heavy tables may use `bigint generated always as identity` if write throughput or storage efficiency becomes a concern, but the first migration should stay on `uuid` for consistency
- timestamps use `timestamptz`
- flexible metadata uses `jsonb`
- large payloads stay in S3 and are referenced by URI from Aurora

Dependency tables assumed by this schema:
- `users`
- `courses`
- `sections`
- `section_memberships`
- `course_corpus_versions`

#### `tutor_sessions`

Purpose:
- one persistent tutoring session for a student inside a specific section/course/assignment/week context

Columns:
- `id uuid primary key`
- `student_user_id uuid not null references users(id)`
- `section_id uuid not null references sections(id)`
- `course_id uuid not null references courses(id)`
- `course_corpus_version_id uuid null references course_corpus_versions(id)`
- `client_kind text not null`
- `assignment_slug text null`
- `week_slug text null`
- `source_session_key text null`
- `status text not null`
- `started_at timestamptz not null`
- `last_activity_at timestamptz not null`
- `ended_at timestamptz null`
- `latest_turn_index integer not null default 0`
- `flagged_turn_count integer not null default 0`
- `hint_count integer not null default 0`
- `compile_count integer not null default 0`
- `metadata jsonb not null default '{}'::jsonb`

Allowed values:
- `client_kind`: `web`, `extension`
- `status`: `active`, `ended`, `abandoned`

Indexes:
- `(student_user_id, last_activity_at desc)`
- `(section_id, last_activity_at desc)`
- `(course_id, week_slug, assignment_slug)`
- partial index on `(status)` where `status = 'active'`

#### `tutor_turns`

Purpose:
- one student prompt / assistant answer cycle within a session

Columns:
- `id uuid primary key`
- `session_id uuid not null references tutor_sessions(id) on delete cascade`
- `student_user_id uuid not null references users(id)`
- `section_id uuid not null references sections(id)`
- `course_id uuid not null references courses(id)`
- `course_corpus_version_id uuid null references course_corpus_versions(id)`
- `turn_index integer not null`
- `request_origin text not null`
- `user_message_text text not null`
- `final_answer_text text null`
- `final_status text not null`
- `guardrail_action text null`
- `started_at timestamptz not null`
- `completed_at timestamptz null`
- `latency_ms integer null`
- `retrieved_chunk_count integer null`
- `citation_count integer null`
- `raw_prompt_s3_uri text null`
- `raw_response_s3_uri text null`
- `metadata jsonb not null default '{}'::jsonb`

Allowed values:
- `request_origin`: `web`, `extension`
- `final_status`: `answered`, `guardrail_replaced`, `blocked`, `errored`
- `guardrail_action`: `pass`, `log_only`, `replace`

Constraints:
- unique `(session_id, turn_index)`

Indexes:
- `(session_id, turn_index)`
- `(student_user_id, started_at desc)`
- `(section_id, started_at desc)`
- partial index on `(final_status)` where `final_status in ('guardrail_replaced', 'errored')`

#### `telemetry_events`

Purpose:
- append-only coarse client telemetry generated by the web app or VS Code extension

Columns:
- `id uuid primary key`
- `session_id uuid null references tutor_sessions(id) on delete cascade`
- `turn_id uuid null references tutor_turns(id) on delete cascade`
- `student_user_id uuid not null references users(id)`
- `section_id uuid not null references sections(id)`
- `course_id uuid not null references courses(id)`
- `event_source text not null`
- `event_name text not null`
- `client_event_id text not null`
- `occurred_at_client timestamptz not null`
- `received_at_server timestamptz not null`
- `assignment_slug text null`
- `week_slug text null`
- `payload jsonb not null default '{}'::jsonb`

Allowed values:
- `event_source`: `web`, `extension`

Constraints:
- unique `(event_source, client_event_id)`

Indexes:
- `(session_id, occurred_at_client)`
- `(turn_id, occurred_at_client)`
- `(student_user_id, occurred_at_client desc)`
- `(section_id, event_name, occurred_at_client desc)`

#### `pipeline_step_events`

Purpose:
- append-only backend trace rows for each meaningful stage in one tutoring turn

Columns:
- `id uuid primary key`
- `session_id uuid not null references tutor_sessions(id) on delete cascade`
- `turn_id uuid not null references tutor_turns(id) on delete cascade`
- `student_user_id uuid not null references users(id)`
- `section_id uuid not null references sections(id)`
- `course_id uuid not null references courses(id)`
- `step_name text not null`
- `attempt_index integer not null default 1`
- `provider text null`
- `route_name text null`
- `model_name text null`
- `endpoint_name text null`
- `started_at timestamptz not null`
- `completed_at timestamptz null`
- `latency_ms integer null`
- `success boolean not null`
- `error_code text null`
- `error_message text null`
- `raw_trace_s3_uri text null`
- `summary jsonb not null default '{}'::jsonb`

Allowed values:
- `step_name`: `request_received`, `retrieval`, `llm_inference`, `guardrail`, `answer_returned`

Constraints:
- unique `(turn_id, step_name, attempt_index)`

Indexes:
- `(turn_id, step_name)`
- `(session_id, started_at)`
- `(section_id, step_name, started_at desc)`
- partial index on `(step_name, success)` where `success = false`

#### `analytics_student_daily`

Purpose:
- low-cost dashboard reads grouped by student and day without scanning raw events

Columns:
- `id uuid primary key`
- `metric_date date not null`
- `student_user_id uuid not null references users(id)`
- `section_id uuid not null references sections(id)`
- `course_id uuid not null references courses(id)`
- `sessions_started integer not null default 0`
- `sessions_active integer not null default 0`
- `turns_count integer not null default 0`
- `hints_requested integer not null default 0`
- `compile_requests integer not null default 0`
- `compile_failures integer not null default 0`
- `guardrail_replacements integer not null default 0`
- `stuck_signals integer not null default 0`
- `active_minutes integer not null default 0`
- `last_activity_at timestamptz null`

Constraints:
- unique `(metric_date, student_user_id, section_id)`

Indexes:
- `(section_id, metric_date desc)`
- `(course_id, metric_date desc)`

#### `analytics_section_daily`

Purpose:
- professor/admin section-level aggregates for the analytics frontend

Columns:
- `id uuid primary key`
- `metric_date date not null`
- `section_id uuid not null references sections(id)`
- `course_id uuid not null references courses(id)`
- `unique_students_active integer not null default 0`
- `sessions_started integer not null default 0`
- `turns_count integer not null default 0`
- `hints_requested integer not null default 0`
- `compile_requests integer not null default 0`
- `compile_failures integer not null default 0`
- `guardrail_replacements integer not null default 0`
- `flagged_sessions_count integer not null default 0`
- `stuck_students_count integer not null default 0`
- `avg_turn_latency_ms integer null`

Constraints:
- unique `(metric_date, section_id)`

Indexes:
- `(section_id, metric_date desc)`
- `(course_id, metric_date desc)`

Retention and storage policy:
- Aurora stores normalized summaries, identifiers, and joinable metrics
- S3 stores raw prompt/context/code/trace payloads referenced by URI
- `telemetry_events` and `pipeline_step_events` should support archival or partition-aware retention later, but retention policy can be implemented after the first production cut

### Pending 2: backend tracing contract for retrieval, llm_inference, guardrail, and answer_returned

Status:
- pending

Scope:
- standardize one backend event envelope so every tutoring turn can be reconstructed and evaluated without scraping free-form logs

Required event envelope:
- `trace_id uuid`
- `session_id uuid`
- `turn_id uuid`
- `student_user_id uuid`
- `section_id uuid`
- `course_id uuid`
- `step_name text`
- `attempt_index integer`
- `started_at timestamptz`
- `completed_at timestamptz`
- `latency_ms integer`
- `success boolean`
- `provider text`
- `route_name text`
- `model_name text`
- `endpoint_name text`
- `error_code text null`
- `error_message text null`
- `raw_trace_s3_uri text null`
- `summary jsonb`

Implementation rule:
- every tutoring request writes one `pipeline_step_events` row per stage
- the backend should emit the row even on failure; `success = false` plus `error_code` is required
- raw stage payloads should be written to S3 only when needed for audit/eval/debug

#### `retrieval` contract

Purpose:
- capture what corpus was queried and what came back from Qdrant

Required `summary` fields:
- `course_corpus_version_id`
- `content_collection_name`
- `guidelines_collection_name`
- `query_strategy`
- `top_k_requested`
- `top_k_returned`
- `retrieved_chunk_ids`
- `retrieved_document_ids`
- `retrieval_filter`
- `qdrant_latency_ms`

Optional `summary` fields:
- `embedding_model`
- `reranker_model`
- `cache_hit`

#### `llm_inference` contract

Purpose:
- capture the SageMaker Async draft-generation step

Required `summary` fields:
- `sagemaker_endpoint_name`
- `invocation_mode`
- `request_s3_uri`
- `response_s3_uri`
- `poll_attempts`
- `output_status`

Optional `summary` fields when available:
- `input_token_count`
- `output_token_count`
- `finish_reason`
- `cold_start_suspected`

Expected values:
- `invocation_mode`: `sagemaker_async`
- `output_status`: `completed`, `timeout`, `failed`

#### `guardrail` contract

Purpose:
- capture the semantic/rule-based post-LLM check outcome

Required `summary` fields:
- `guardrail_route`
- `v1_rule_result`
- `v2_score`
- `action`
- `replacement_applied`
- `reason_codes`

Optional `summary` fields:
- `sagemaker_endpoint_name`
- `onnx_model_version`
- `policy_bundle_version`

Expected values:
- `action`: `pass`, `log_only`, `replace`
- `guardrail_route`: `sagemaker_serverless`, `sagemaker_realtime`

#### `answer_returned` contract

Purpose:
- capture the final response that the student actually received

Required `summary` fields:
- `final_status`
- `response_kind`
- `citation_count`
- `answer_char_count`
- `returned_to_client`

Optional `summary` fields:
- `client_error_code`
- `streaming_enabled`

Expected values:
- `final_status`: `answered`, `blocked`, `errored`
- `response_kind`: `socratic_hint`, `guardrail_rewrite`, `policy_block`, `system_error`

### Pending 3: frontend and extension telemetry contract

Status:
- pending

Scope:
- define the coarse client telemetry the web app and VS Code extension are allowed to emit

Rules:
- no raw keystroke streams
- no continuous cursor-position logging
- no full file contents in telemetry events
- no clipboard capture
- code snapshots may be sent only as part of explicit tutor/help flows or compile/test flows and should be stored as trace payloads, not generic telemetry

Required common event envelope:
- `client_event_id string`
- `event_source string`
- `event_name string`
- `occurred_at_client string`
- `session_id string`
- `turn_id string | null`
- `course_id string`
- `section_id string`
- `assignment_slug string | null`
- `week_slug string | null`
- `app_version string`
- `payload object`

Allowed `event_source` values:
- `web`
- `extension`

Allowed event families:

1. session lifecycle
- `session_started`
- `session_resumed`
- `session_ended`

Required payload fields:
- `launch_surface`
- `client_kind`

2. tutor interaction
- `hint_requested`
- `hint_received`
- `citation_opened`
- `follow_up_requested`

Required payload fields:
- `request_mode`
- `message_char_count`

Optional payload fields:
- `latency_ms`
- `citation_index`

3. compile/test workflow
- `compile_requested`
- `compile_completed`
- `test_requested`
- `test_completed`

Required payload fields:
- `language`
- `success`

Optional payload fields:
- `public_test_count`
- `public_tests_passed`
- `compiler_error_count`

4. editor/workspace presence
- `file_opened`
- `assignment_changed`
- `heartbeat_snapshot`
- `stuck_signal`

Required payload fields by event:
- `file_opened`: `language`, `file_role`
- `assignment_changed`: `previous_assignment_slug`, `next_assignment_slug`
- `heartbeat_snapshot`: `active_minutes_bucket`, `is_idle`, `dirty_file_count`, `compile_count_since_last_heartbeat`
- `stuck_signal`: `reason_code`, `minutes_without_progress`

Collection policy:
- `heartbeat_snapshot` no more than once every 60 seconds while active
- `file_opened` only when the active file meaningfully changes
- client retries must preserve `client_event_id` for backend deduplication
- telemetry should tolerate offline buffering and later replay from the extension

### Pending 4: companion implementation plan for course registry and explicit course routing

Status:
- pending

Goal:
- remove implicit/default course selection from the online tutor path and make every retrieval operation resolve through a registry-backed course decision

Deliverables:
- Aurora schema and migrations for:
  - `courses`
  - `sections`
  - `section_memberships`
  - `course_corpus_versions`
- backend models/repositories for those tables
- one explicit course-resolution path inside the tutoring request flow
- admin/professor read APIs for course/section membership and active corpus status

Implementation steps:
1. add relational models and migrations for course registry entities
2. seed existing MIT and Harvard collections as first managed `course_corpus_versions`
3. add backend resolver logic:
   - derive student section membership from authenticated identity
   - derive active `course_id`
   - derive active `course_corpus_version_id`
   - derive the target Qdrant collection names
4. remove reliance on default `course_source` in the online chat path
5. reject requests when active course resolution is ambiguous or missing
6. add trace fields so every retrieval step records the resolved course/corpus version
7. add tests for:
   - successful routing for MIT/Harvard
   - successful routing for one uploaded course
   - missing membership
   - stale or inactive corpus version

Acceptance criteria:
- no production request reaches retrieval with an implicit default course
- every tutoring turn stores the resolved `course_id`, `section_id`, and `course_corpus_version_id`
- professor/admin views can query ingestion readiness by course/section

Likely affected areas:
- backend auth/user-context code
- `rag_eng/service.py`
- retrieval/config repositories
- admin endpoints
- analytics queries

### Pending 5: implementation plan for the guardrail SageMaker endpoint

Status:
- pending

Goal:
- productionize the semantic guardrail as a SageMaker-hosted inference component callable by the backend after the tutor draft returns

Deliverables:
- packaged guardrail model artifact
- SageMaker inference container or script mode package
- backend client wrapper around the endpoint
- guardrail stage traces and error handling

Implementation steps:
1. define the model input/output payload from the existing guardrail logic
2. adapt `output_guardrails/semantic_guardrail.py` into a SageMaker-compatible inference entrypoint
3. package the first version using existing Python runtime expectations
4. benchmark memory and latency on SageMaker Serverless Inference
5. if serverless cold starts or limits are unacceptable, switch the same contract to a small real-time endpoint
6. add ONNX Runtime export and benchmarking as the hardening path, not the blocking first step
7. implement a backend client wrapper that:
   - calls the endpoint
   - converts endpoint response into the internal `POST /score` contract
   - records a `guardrail` step event and optional raw trace URI
8. add fallback policy for endpoint failure:
   - either fail closed with safe replacement
   - or fail open with explicit logging, depending on product policy

Acceptance criteria:
- backend can call the guardrail endpoint synchronously after tutor draft generation
- endpoint returns `pass`, `log_only`, or `replace`
- latency/error metrics are visible in CloudWatch and `pipeline_step_events`
- the backend can swap between serverless and real-time without changing its internal contract

Likely affected areas:
- `output_guardrails/`
- backend inference client layer
- backend tracing/wrapper code
- deployment scripts/infrastructure config

### Pending 6: implementation plan for the SageMaker Processing chunk/index pipeline

Status:
- pending

Goal:
- convert parsed S3 document envelopes into chunked, embedded, versioned course corpora stored in Qdrant Cloud

Deliverables:
- one Processing entrypoint that reads parser envelopes from S3
- chunking logic aligned with current RAG retrieval needs
- embedding + Qdrant upsert logic
- status handoff back into Aurora `course_corpus_versions`

Implementation steps:
1. define the parsed envelope schema consumed from `parsed_json/<course_id>/`
2. implement a Processing job entrypoint that:
   - reads envelopes from S3
   - normalizes text blocks
   - creates deterministic chunk IDs
   - preserves provenance to original S3 object and parsed envelope
3. select the embedding model/provider used for indexing and record its version in metadata
4. upsert chunks and metadata into the target Qdrant collection
5. write prepared chunk artifacts and job summaries back to S3
6. update `course_corpus_versions` status only after successful upsert completion
7. add idempotency rules so reruns do not duplicate chunks
8. add processing-job status polling and surfacing through backend admin APIs

Acceptance criteria:
- one uploaded course can move from parsed envelopes to a retrievable Qdrant collection without manual local scripts
- every indexed chunk is traceable back to source file and corpus version
- failed jobs leave the prior active corpus version intact
- admin/professor visibility can show `pending`, `processing`, `ready`, or `failed` corpus status

Likely affected areas:
- `data_ingestion/`
- RAG indexing code
- backend admin job launch/status endpoints
- course registry persistence

## Operational Readiness and Health

`/health` should evolve to include:
- Qdrant configured/reachable
- selected inference route
- guardrail endpoint reachability
- SageMaker tutor route configured
- current course registry availability

Add CloudWatch logs and alarms for:
- ALB 4xx/5xx
- ECS backend task health
- Aurora connection saturation / error alarms
- SageMaker Async failures and backlog
- guardrail endpoint latency / error rate
- parser Processing job failures
- chunk/index Processing job failures
- evaluation Processing job failures

## Test Plan

## Online path

- warm SageMaker Async tutor request
- cold SageMaker Async tutor request after scale-to-zero
- guardrail endpoint `pass`
- guardrail endpoint `log_only`
- guardrail endpoint `replace`
- explicit routing to MIT course collection
- explicit routing to Harvard course collection
- explicit routing to one teacher-uploaded course collection
- missing course mapping fails safely and visibly
- session start / resume / end persists correctly
- one turn produces relational step events for retrieval, LLM, guardrail, and final answer

## Offline ingestion

- upload files to `teacher_uploads/<course_id>/`
- parser Processing job writes valid envelopes to `parsed_json/<course_id>/`
- chunk/index Processing job converts envelopes into retrievable chunks
- Qdrant collection is created or updated correctly
- course registry marks ingestion success only after index completion

## Analytics

- student-level aggregates can be grouped by section and course
- section-level aggregates can be rendered without scanning raw traces
- flagged sessions are queryable by professor role and section ownership
- raw trace drill-down works by following S3 URIs from Aurora rows

## Evaluation

- evaluation Processing job consumes inputs and writes metrics/artifacts to S3
- guardrail eval path works independently of online traffic
- retrieval eval can target MIT, Harvard, and one uploaded course corpus

## Frontend/browser

- CloudFront serves SPA routes correctly on refresh
- `/api/*` origin routing works
- Cognito login/logout works with production callback URLs
- admin pages can launch and inspect ingestion/eval jobs

## Key Risks and Constraints

- SageMaker Async with scale-to-zero is still the main latency risk.
- The teacher parser is merged, but the S3 envelope -> chunk -> embedding -> Qdrant stage still needs to be implemented as a first-class processing job.
- Dynamic course routing is not deployment-safe until the backend stops relying on implicit/default course selection.
- Analytics are not production-ready until Aurora-backed session + telemetry capture exists.
- Full prompt/code/message trace storage introduces privacy and retention obligations; raw traces should be access-controlled and retention-scoped.
- The extension path still needs a production-safe auth story if it is to act outside browser Cognito session assumptions.
- SageMaker Serverless Inference may be sufficient for the guardrail, but it still needs benchmarking. If cold starts or memory limits are unacceptable, move the guardrail to a small real-time SageMaker endpoint.
- Qdrant Cloud remains an external dependency even if it is free-tier funded; if that exception stops being acceptable, the vector layer will need a later AWS-native migration.
- OpenAI and Cohere should not become silent production dependencies; if they remain enabled, they must stay clearly labeled as testing-only.
- Any future hosted model replacement that is not your own fine-tuned SageMaker model should preferentially move to Amazon Bedrock rather than remain on external paid APIs.

## Final Defaults Chosen

- Frontend: S3 + CloudFront
- Backend orchestrator: ECS Fargate + ALB
- Application database: Aurora PostgreSQL Serverless v2 direct connection for MVP
- RDS Proxy: deferred until needed
- Main tutor model: SageMaker Async
- Guardrail runtime: SageMaker AI endpoint
- First guardrail serving candidate: SageMaker Serverless Inference
- Guardrail optimization target: ONNX Runtime
- Offline parser / chunk / eval jobs: SageMaker Processing
- Vector DB: Qdrant Cloud free tier as an accepted external exception
- External hosted-model providers: OpenAI/Cohere testing-only
- Future hosted-model replacement path: Amazon Bedrock where appropriate
- Scheduled automation: EventBridge Scheduler
- Course registry: Aurora PostgreSQL
- Dynamic uploaded courses: included in scope
- Teacher parser: official parse stage
- Queryable session analytics: Aurora PostgreSQL
- Raw traces and large telemetry payloads: S3
- Redis: deferred

## References

- SageMaker Async Inference: https://docs.aws.amazon.com/sagemaker/latest/dg/async-inference.html
- SageMaker Processing: https://docs.aws.amazon.com/sagemaker/latest/dg/processing-job.html
- SageMaker Serverless Inference: https://docs.aws.amazon.com/sagemaker/latest/dg/serverless-endpoints.html
- SageMaker Batch Transform: https://docs.aws.amazon.com/sagemaker/latest/dg/batch-transform.html
