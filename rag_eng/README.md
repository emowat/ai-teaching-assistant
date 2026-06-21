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
| `POST` | `/api/chat` | none | chat / VS Code extension endpoint |
| `POST` | `/run/compile` | bearer | compile + run C++ code |
| `GET` | `/gradio` | browser | Gradio diagnostic console |
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

8. Start the service:

```bash
uv run uvicorn rag_eng.main:app --host 0.0.0.0 --port 8001
```

## Common runtime examples

### `GET /health`

Use this to confirm the backend, Qdrant, Aurora, and model provider wiring.

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

- retrieval presets
- top-k / final result count controls
- rerank strategy selection
- route / trace overrides
- a guardrail console

Use `Experiment baseline (K=8, similarity)` as the default-safe preset.

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
| `RESTART_COMMAND` | — | optional backend restart command |

The editable non-secret route settings live in `rag_eng/runtime_config.yaml`.
