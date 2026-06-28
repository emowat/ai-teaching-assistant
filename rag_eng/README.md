# `rag_eng`

FastAPI service layer for the codingrabbit.dev capstone. It owns:

- RAG query execution
- authenticated user profile lookup
- admin course / ingestion control-plane APIs
- the C++ compile-run sandbox API
- the Gradio diagnostic console

## API docs

- OpenAPI docs: `http://localhost:8001/docs`
- Human workflow guide: [docs/api_workflows.md](/home/user/MIDS/w210/capstone/docs/api_workflows.md)

The OpenAPI page is useful for schemas. The workflow guide is the better source
for copy-paste admin calls.

## Auth model

There are three auth patterns in the service today:

| Surface | Auth model |
|---|---|
| `GET /health`, `POST /query`, `POST /api/chat` | currently unauthenticated |
| `GET /me`, `POST /run/compile` | Cognito bearer token |
| most `/admin/*` routes | admin Cognito bearer token or `X-Admin-Token` |
| `POST /admin/index/ensure`, `POST /admin/index/rebuild` | `X-Admin-Token` only |

`POST /query` and `POST /api/chat` now run the pre-RAG input guardrail before
retrieval. If the guardrail blocks a request, the service short-circuits and
returns a safe redirect response without spending retrieval or inference
compute.

The orchestrator keeps the session-level warning count in Aurora under
`tutor_sessions.metadata` using the `Session_Adversarial_Warnings` family of
keys. The warning and end-chat thresholds are configured in
[`runtime_config.yaml`](./runtime_config.yaml)
under `runtime.input_guardrail_orchestration`, and every persisted turn snapshot
now records the policy snapshot plus the session state before and after the
orchestrator decision.

Aurora is also the source of truth for application users, sections, and
section memberships. Cognito still handles authentication and the coarse
global role, but the `/admin/users`, `/admin/sections`, and `/professor/*`
routes read from the Aurora-backed application registry.

Admin bearer auth means:

- `Authorization: Bearer <access-token>`
- token must resolve to a Cognito user whose primary role is `admin`

Legacy admin token auth means:

- `X-Admin-Token: <ADMIN_TOKEN>`

If `ADMIN_TOKEN` is configured, the course, ingestion, and LLM-config admin
routes accept either auth style.

## Endpoint inventory

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/health` | none | readiness plus dependency status |
| `GET` | `/me` | bearer | current authenticated user / role |
| `POST` | `/query` | none | RAG query with reranking |
| `POST` | `/api/chat` | none | full pipeline chat / VS Code extension endpoint |
| `POST` | `/run/compile` | bearer | compile + run C++ code |
| `GET` | `/gradio` | browser | Gradio diagnostic console, including the Input Guardrail tab |
| `GET` | `/admin/courses` | admin bearer or `X-Admin-Token` | list courses |
| `GET` | `/admin/courses/{course_id}` | admin bearer or `X-Admin-Token` | get one course |
| `POST` | `/admin/courses` | admin bearer or `X-Admin-Token` | create course |
| `PATCH` | `/admin/courses/{course_id}` | admin bearer or `X-Admin-Token` | update course |
| `POST` | `/admin/courses/{course_id}/aliases` | admin bearer or `X-Admin-Token` | add aliases |
| `DELETE` | `/admin/courses/{course_id}/aliases/{alias}` | admin bearer or `X-Admin-Token` | deactivate alias |
| `GET` | `/admin/courses/{course_id}/documents` | admin bearer or `X-Admin-Token` | list uploaded source files |
| `POST` | `/admin/courses/{course_id}/documents/upload-url` | admin bearer or `X-Admin-Token` | create presigned S3 upload URL |
| `DELETE` | `/admin/courses/{course_id}/documents` | admin bearer or `X-Admin-Token` | delete a source file by `key` |
| `GET` | `/admin/courses/{course_id}/corpus-versions` | admin bearer or `X-Admin-Token` | list corpus build history |
| `GET` | `/admin/users` | admin bearer or `X-Admin-Token` | list application users with memberships |
| `POST` | `/admin/users` | admin bearer or `X-Admin-Token` | create an invited application user |
| `PATCH` | `/admin/users/{user_id}` | admin bearer or `X-Admin-Token` | update a user’s role or status |
| `GET` | `/admin/sections` | admin bearer or `X-Admin-Token` | list sections with roster summaries |
| `POST` | `/admin/sections` | admin bearer or `X-Admin-Token` | create a section in Aurora |
| `PATCH` | `/admin/sections/{section_id}` | admin bearer or `X-Admin-Token` | update section metadata |
| `POST` | `/admin/sections/{section_id}/memberships` | admin bearer or `X-Admin-Token` | assign a user to a section |
| `PATCH` | `/admin/sections/{section_id}/memberships/{user_id}` | admin bearer or `X-Admin-Token` | update a section membership |
| `GET` | `/professor/sections` | bearer | list sections visible to the current professor/TA |
| `GET` | `/professor/sections/{section_id}/students` | bearer | list active students and live usage fields |
| `GET` | `/admin/ingestion/jobs` | admin bearer or `X-Admin-Token` | list recent ingestion jobs |
| `POST` | `/admin/ingestion/launch` | admin bearer or `X-Admin-Token` | launch ECS ingestion task |
| `GET` | `/admin/ingestion/jobs/{job_id}` | admin bearer or `X-Admin-Token` | inspect one ingestion job |
| `GET` | `/admin/llm/config` | admin bearer or `X-Admin-Token` | read LLM routing config |
| `POST` | `/admin/llm/config` | admin bearer or `X-Admin-Token` | save LLM routing config |
| `POST` | `/admin/restart` | admin bearer or `X-Admin-Token` | reload config or schedule restart |
| `POST` | `/admin/index/ensure` | `X-Admin-Token` | ensure local index |
| `POST` | `/admin/index/rebuild` | `X-Admin-Token` | rebuild local index |

## Local setup

1. Copy `.env.example` to `.env` at the repo root.
2. Fill in:
   - `QDRANT_URL`
   - `QDRANT_API_KEY`
   - `COHERE_API_KEY`
   - Cognito variables
3. If you use OpenAI routes, also fill in:
   - `OPENAI_API_KEY`
   - optionally `OPENAI_BASE_URL`
4. If you use Bedrock, fill in:
   - `AWS_REGION`
   - optionally `AWS_PROFILE`
5. Install dependencies:

```bash
uv sync
# or
pip install -r requirements.txt
```

6. If you have Aurora course registry access, verify routing:

```bash
export COURSE_REGISTRY_DATABASE_URL="postgresql://user:password@aurora-endpoint:5432/postgres?sslmode=require"
uv run python -m rag_eng.cli resolve-course --course-id mit-14
uv run python -m rag_eng.cli resolve-course --course-source cs50
```

7. If you want the admin ingestion workflow to launch ECS tasks, set:

```bash
export INGESTION_ECS_CLUSTER=...
export INGESTION_ECS_TASK_DEFINITION=...
export INGESTION_ECS_CONTAINER_NAME=ingestion-worker
export INGESTION_ECS_SUBNETS=subnet-...,subnet-...
export INGESTION_ECS_SECURITY_GROUPS=sg-...
export INGESTION_JOBS_DATABASE_URL="postgresql://user:password@aurora-endpoint:5432/postgres?sslmode=require"
```

8. If you want the input guardrail model stage active, restore the checkpoint:

```bash
./deploy/scripts/restore-input-guardrail-checkpoint.sh
```

By default this downloads from `s3://codingrabbit-data-dev/models/guardrails/input_codebert_v1/`
into `input_guardrails/models/checkpoints/input_codebert_v1`.
If that S3 location is a prefix containing `model.tar.gz`, the restore helper
will extract the archive into the local checkpoint directory automatically.

For the ECS deployment, both the input and output guardrail checkpoints are
restored automatically at container startup by `deploy/scripts/rag-eng-startup.sh`,
which also starts `uvicorn` with proxy headers enabled. The ECS task definition
sets `GRADIO_ROOT_PATH=/gradio` and `GRADIO_PUBLIC_ORIGIN` to the public
CloudFront origin so Gradio emits HTTPS-safe asset and API links without
breaking the mounted route.
The container image stays small because the checkpoints are loaded from S3 at
runtime instead of being baked into the image.
If `RUNTIME_CONFIG_S3_URI` is set, the same startup path restores
[`runtime_config.yaml`](./runtime_config.yaml) from S3 before the app starts,
and `POST /admin/llm/config` syncs saved routing changes back to that object
so the admin model selection survives ECS task replacement.

9. Start the service:

```bash
uv run uvicorn rag_eng.main:app --host 0.0.0.0 --port 8001
```

The local server port stays aligned with the ECS container port. Runtime
behavior knobs remain in `rag_eng/runtime_config.yaml`; AWS service wiring
for the online orchestrator is in `deploy/deployment.yaml` under
`rag_eng_ecs`.

10. If you want to export offline-eval turn logs from Aurora to S3, use:

```bash
uv run python -m rag_eng.cli export-turn-snapshots \
  --database-url "$COURSE_REGISTRY_DATABASE_URL" \
  --bucket "$S3_DATA_BUCKET" \
  --start-date 2026-06-23 \
  --end-date 2026-06-23
```

By default the exporter writes JSONL files under:

```text
eval/chat_logs/turn_logs/date=YYYY-MM-DD/turn_snapshots.jsonl
```

If you pass `--course-id`, the exporter adds a `course_id=...` partition
between the prefix and the date partition.

The export destination and Aurora query timeout are configured in
[`runtime_config.yaml`](./runtime_config.yaml) under
`runtime.chat_log_export`. `--bucket` and `--connect-timeout-seconds` still
override those defaults for one-off runs.

Each exported turn snapshot includes the `policy_snapshot` and the
`orchestrator_phase` block, which makes it easier to audit whether a turn was
handled by the input guardrail, a session-level end-chat decision, or the main
model path.

## Validation

Run the full repository test suite from the repo root:

```bash
uv run pytest -q
```

If you want to run the known stable test roots explicitly, use:

```bash
uv run pytest -q test input_guardrails/tests output_guardrails rag/experiments/test_labeling_chunks.py
```

For local service work, these focused checks are the most useful:

```bash
uv run pytest -q test/test_rag_eng_service.py test/test_rag_eng_api.py
uv run pytest -q test/test_offline_eval_smoke.py
uv run pytest -q test/test_offline_eval_live_smoke.py
```

Lint and formatting checks:

```bash
uv run ruff check rag_eng test
git diff --check
```

## Common runtime examples

### `GET /health`

Use this to confirm the backend, Qdrant, Aurora, and model provider wiring.
The admin dashboard polls this endpoint periodically and uses the configured
and reachable flags to populate the health badge tooltip.

```bash
curl -s http://localhost:8001/health
```

### `GET /me`

```bash
curl -s http://localhost:8001/me \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

### `POST /query`

```bash
curl -s http://localhost:8001/query \
  -H 'Content-Type: application/json' \
  -d '{
    "student_message": "Why does my pointer crash?",
    "code_raw": "int* p; *p = 5;",
    "terminal_output": "Segmentation fault",
    "week": 3,
    "mode": "Homework Assist",
    "course_id": "mit14",
    "result_count": 8,
    "rerank_strategy": "similarity"
  }'
```

The query endpoint now runs the input guardrail before retrieval. If the input
is blocked, the response returns the guardrail metadata plus a safe redirect
answer and no retrieval context.

### `POST /run/compile`

```bash
curl -s http://localhost:8001/run/compile \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "files": {
      "main.cpp": "#include <iostream>\nint main(){std::cout << 42 << \"\\n\";}"
    },
    "entrypoint": "main.cpp",
    "mode": "compile",
    "stdin": ""
  }'
```

### `POST /api/chat`

```bash
curl -s http://localhost:8001/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "codingrabbit-ta",
    "course_id": "mit14",
    "messages": [
      {"role": "user", "content": "Explain why this pointer crashes."}
    ],
    "stream": false
  }'
```

This is the full pipeline path:

1. input guardrail
2. retrieval
3. prompt assembly
4. inference
5. output guardrails

If the input guardrail blocks the request, the backend skips retrieval and
inference and returns the safe redirect response immediately.

### Admin diagnostics

The backend also exposes admin-only, non-persisting probes for stage-by-stage
inspection. These call the same service logic as the public endpoints but do
not write turn snapshots or session state.

- `POST /admin/diagnostics/input-guardrail`
- `POST /admin/diagnostics/rag`
- `POST /admin/diagnostics/output-guardrail`
- `POST /admin/diagnostics/pipeline`

Example:

```bash
curl -s http://localhost:8001/admin/diagnostics/pipeline \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "codingrabbit-ta",
    "course_id": "mit14",
    "messages": [
      {"role": "user", "content": "Explain why this pointer crash is undefined behavior."}
    ],
    "stream": false
  }'
```

Use these diagnostics for black-box checks in tests and operations. Keep `/health`
focused on readiness and dependency reachability.

## Admin workflows

For the full course creation, document upload, parse, and chunk-index flow, use:

- [docs/api_workflows.md](/home/user/MIDS/w210/capstone/docs/api_workflows.md)

That guide includes:

- course CRUD
- presigned document upload
- S3 document deletion
- ingestion job launch and polling
- corpus version inspection
- LLM config reads/writes

## Gradio diagnostics

The Gradio backend console exposes:

- input guardrail inspection
- retrieval presets
- top-k / final result count controls
- rerank strategy selection
- route / trace overrides
- a guardrail console

The Input Guardrail tab is the quickest way to inspect the new pre-RAG model
decision before the request reaches retrieval.

Use `Experiment baseline (K=8, similarity)` as the default-safe preset.

## Offline eval exports

The per-turn snapshot table can be exported to S3 JSONL for offline evaluation
jobs and LLM-as-a-judge tooling.

```bash
uv run python -m rag_eng.cli export-turn-snapshots \
  --database-url "$COURSE_REGISTRY_DATABASE_URL" \
  --bucket "$S3_DATA_BUCKET" \
  --prefix eval/chat_logs/turn_logs \
  --start-date 2026-06-23 \
  --end-date 2026-06-23
```

The exported JSONL records are the canonical turn snapshots captured in
`tutor_turn_snapshots`; each line includes the trace ids, course metadata,
input/output guardrail phases, retrieval metadata, and final rendered text.

## C++ sandbox security constraints

When `RUNNER_MODE=docker`, the runner uses:

- `--network none`
- `--read-only`
- `--tmpfs /workspace:size=32m,noexec`
- `--memory 128m --cpus 1 --pids-limit 64`
- `--cap-drop ALL --security-opt no-new-privileges`
- non-root user `runner` (uid `10001`)

Build the runner image before using docker mode:

```bash
./scripts/build-runner.sh
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `APP_PORT` | `8001` | local server port and ECS container port |
| `RUNNER_MODE` | `docker` | `docker` or `subprocess` |
| `RUNNER_IMAGE` | `codingrabbit-cpp-runner:0.1` | Docker image tag |
| `CORS_ORIGINS` | `http://localhost:5173` | allowed browser origins |
| `LOG_LEVEL` | `INFO` | Uvicorn log level |
| `ADMIN_TOKEN` | — | legacy admin token header value |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | optional OpenAI-compatible base URL |
| `AWS_REGION` | `us-east-1` | AWS region for Bedrock and ECS helpers |
| `AWS_PROFILE` | — | optional AWS profile |
| `COURSE_REGISTRY_DATABASE_URL` | — | Aurora/PostgreSQL URL for course routing |
| `DATABASE_URL` | — | fallback Aurora/PostgreSQL URL |
| `RUNTIME_CONFIG_S3_URI` | — | optional `s3://bucket/key` object used to restore and persist `runtime_config.yaml` |
| `INGESTION_ECS_CLUSTER` | — | ECS cluster for on-demand ingestion |
| `INGESTION_ECS_TASK_DEFINITION` | — | ECS task definition |
| `INGESTION_ECS_CONTAINER_NAME` | `ingestion-worker` | container name inside the task definition |
| `INGESTION_ECS_LAUNCH_TYPE` | `FARGATE` | ECS launch type |
| `INGESTION_ECS_PLATFORM_VERSION` | `LATEST` | ECS platform version |
| `INGESTION_ECS_ASSIGN_PUBLIC_IP` | `ENABLED` | public IP assignment |
| `INGESTION_ECS_SUBNETS` | — | comma-separated subnets |
| `INGESTION_ECS_SECURITY_GROUPS` | — | comma-separated security groups |
| `INGESTION_JOBS_DATABASE_URL` | — | Aurora/PostgreSQL URL for ingestion job tracking |
| `INGESTION_JOBS_CONNECT_TIMEOUT_SECONDS` | `5` | DB connect timeout for job tracking |
| `INPUT_GUARDRAILS_ENABLED` | `true` | enable the pre-RAG input guardrail model stage |
| `INPUT_GUARDRAILS_CODEBERT_S3_URI` | `s3://codingrabbit-data-dev/models/guardrails/input_codebert_v1/` | S3 checkpoint or tarball for the input guardrail model |
| `INPUT_GUARDRAILS_CODEBERT_CHECKPOINT_DIR` | `input_guardrails/models/checkpoints/input_codebert_v1` | local Hugging Face checkpoint directory |
| `INPUT_GUARDRAILS_CODEBERT_PASS_BELOW` | `0.30` | model score below which the request is treated as pass |
| `INPUT_GUARDRAILS_CODEBERT_BLOCK_ABOVE` | `0.70` | model score above which the request is blocked |
| `RESTART_COMMAND` | — | optional backend restart command |

The editable non-secret route settings live in `rag_eng/runtime_config.yaml`.
When `RUNTIME_CONFIG_S3_URI` is set, that file is restored from S3 on startup
and saved back to S3 whenever the admin LLM config is updated.
For Bedrock Anthropic Claude Sonnet 4.6, use the inference profile ID
`us.anthropic.claude-sonnet-4-6` (or the global profile ID) instead of the
foundation-model ID `anthropic.claude-sonnet-4-6`.
For Bedrock Anthropic Claude Haiku 4.5, use the inference profile ID
`us.anthropic.claude-haiku-4-5-20251001-v1:0` (or the global profile ID)
instead of the shorter `us.anthropic.claude-haiku-4-5` alias.
Those Sonnet 4.6 and Haiku 4.5 models reject `temperature` and `top_p`
together in Converse, so the service sends `temperature` only for that model
family.
AWS deployment wiring for the online service lives in `deploy/deployment.yaml`
under `rag_eng_ecs`, and the ECS service helper is
[`deploy/scripts/deploy-rag-eng-ecs.sh`](/home/user/MIDS/w210/capstone/deploy/scripts/deploy-rag-eng-ecs.sh).
