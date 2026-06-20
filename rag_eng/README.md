# `rag_eng`

FastAPI service layer for the codingrabbit.dev capstone. Provides the RAG query pipeline, Gradio interrogation UI, and the C++ code execution sandbox API.

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe plus Qdrant/Aurora/LLM dependency status |
| `POST` | `/query` | RAG query with reranking |
| `GET` | `/admin/llm/config` | Read editable LLM provider/model settings |
| `POST` | `/admin/llm/config` | Save editable LLM provider/model settings |
| `POST` | `/admin/restart` | Reload config or schedule a restart command |
| `POST` | `/admin/ingestion/launch` | Launch an on-demand ECS ingestion task |
| `GET` | `/admin/ingestion/jobs/{job_id}` | Inspect an ECS ingestion job |
| `POST` | `/run/compile` | Compile + run student C++ code |
| `GET` | `/gradio` | Gradio RAG interrogation UI |
| `POST` | `/admin/index/ensure` | Idempotent index bootstrap |
| `POST` | `/admin/index/rebuild` | Destructive index rebuild |

## Local setup

1. Copy `.env.example` to `.env` at the repo root.
2. Fill in `QDRANT_URL`, `QDRANT_API_KEY`, `COHERE_API_KEY`, and Cognito variables.
3. Fill in `OPENAI_API_KEY` if you plan to route either chat or RAG through OpenAI.
4. Fill in `AWS_REGION` and optionally `AWS_PROFILE` if you plan to route either
   chat or RAG through Amazon Bedrock.
5. Install dependencies:

```bash
uv sync
# or
pip install -r requirements.txt
```

6. If you have the Aurora course registry URL, verify the runtime lookup path:

```bash
export COURSE_REGISTRY_DATABASE_URL="postgresql://user:password@aurora-endpoint:5432/postgres?sslmode=require"
uv run python -m rag_eng.cli resolve-course --course-id mit-14
uv run python -m rag_eng.cli resolve-course --course-source cs50
```

The `/health` endpoint now reports whether the Aurora-backed course registry is configured and reachable when that env var is present.

7. If you want to launch offline ingestion jobs from the admin API, set the ECS
   runtime values:

```bash
export INGESTION_ECS_CLUSTER=...
export INGESTION_ECS_TASK_DEFINITION=...
export INGESTION_ECS_CONTAINER_NAME=ingestion-worker
export INGESTION_ECS_SUBNETS=subnet-...,subnet-...
export INGESTION_ECS_SECURITY_GROUPS=sg-...
export INGESTION_JOBS_DATABASE_URL="postgresql://user:password@aurora-endpoint:5432/postgres?sslmode=require"
```

The backend registers ingestion jobs in Aurora and launches them as on-demand
ECS Fargate tasks. The worker updates the job row and `course_corpus_versions`
after the ECS task finishes.

8. Ensure or rebuild the index:

```bash
python -m rag_eng.cli ensure-index
```

9. Run the service on port 8001 (frontend default):

```bash
uv run uvicorn rag_eng.main:app --host 0.0.0.0 --port 8001
```

8. Open:
- API docs: `http://localhost:8001/docs`
- Gradio UI: `http://localhost:8001/gradio`

### Gradio diagnostics

The Gradio backend console now exposes retrieval tuning controls in the
Pipeline tab and a dedicated Guardrail Console:

- `Retrieval Preset` for quick experiment-backed configurations
- `Top K / Final Results` for the final retrieved context size
- `Rerank Strategy` for `similarity` or MMR-based reranking
- routing / trace overrides for `course_id`, `session_id`, `request_id`,
  `turn_id`, and `section_id`
- the Guardrail Console for direct V1 + V2 inspection of a draft answer

The pipeline response path now applies output guardrails before returning
the answer. Non-streaming requests are guarded directly; streaming requests
buffer the full draft, guardrail it, then re-chunk the final answer.

Use `Experiment baseline (K=8, similarity)` as the known-good default. The
MMR presets widen candidate fetch internally before reranking.

## C++ sandbox (`POST /run/compile`)

### Request

```json
{
  "files": {
    "linked_list.cpp": "#include <iostream>\n...",
    "main.cpp": "..."
  },
  "options": {
    "entrypoint": "linked_list.cpp"
  }
}
```

### Response

```json
{
  "job_id": "abc123",
  "result": {
    "compile": { "success": true, "stdout": "", "stderr": "", "exit_code": 0, "elapsed_sec": 1.2 },
    "run":     { "success": true, "stdout": "1 -> 2 -> NULL\n", "stderr": "", "exit_code": 0, "elapsed_sec": 0.01 }
  }
}
```

### Runner modes

| `RUNNER_MODE` | Behaviour |
|---|---|
| `docker` (default) | Spawns `codingrabbit-cpp-runner:0.1` in a hardened container (no network, read-only rootfs, 128 MB RAM, 1 CPU, 30 s timeout). |
| `subprocess` | Compiles and runs directly on the host — **development only, unsafe for untrusted code**. |

Build the Docker image before using `docker` mode:

```bash
./scripts/build-runner.sh
```

### Security constraints (docker mode)

- `--network none` — no outbound network
- `--read-only` — immutable rootfs
- `--tmpfs /workspace:size=32m,noexec` — writable scratch space, no execute bit
- `--memory 128m --cpus 1 --pids-limit 64`
- `--cap-drop ALL --security-opt no-new-privileges`
- Runs as non-root user `runner` (uid 10001)

## Key modules

| Module | Description |
|---|---|
| `api.py` | FastAPI app factory, CORS middleware, route definitions |
| `config.py` | `Settings` dataclass (reads from env) |
| `run_schemas.py` | Pydantic models for compile request/response |
| `runner_client.py` | Invokes Docker or subprocess runner, parses results |

## Docker

```bash
docker build -t rag-eng .
docker run --rm -p 8001:8001 --env-file .env rag-eng
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `RUNNER_MODE` | `docker` | `docker` or `subprocess` |
| `RUNNER_IMAGE` | `codingrabbit-cpp-runner:0.1` | Docker image tag |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed CORS origins (comma-separated) |
| `LOG_LEVEL` | `INFO` | Uvicorn log level |
| `ADMIN_TOKEN` | — | Bearer token for admin endpoints |
| `OPENAI_API_KEY` | — | OpenAI API key for admin-selected OpenAI routes |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Optional OpenAI-compatible base URL |
| `AWS_REGION` | `us-east-1` | AWS region used for Bedrock inference profiles |
| `AWS_PROFILE` | — | Optional AWS profile for Bedrock credentials |
| `COURSE_REGISTRY_DATABASE_URL` | — | Optional Aurora/PostgreSQL URL for course registry lookups |
| `DATABASE_URL` | — | Generic Aurora/PostgreSQL fallback URL for course registry lookups |
| `INGESTION_ECS_CLUSTER` | — | ECS cluster name for on-demand ingestion tasks |
| `INGESTION_ECS_TASK_DEFINITION` | — | ECS task definition for the ingestion worker |
| `INGESTION_ECS_CONTAINER_NAME` | `ingestion-worker` | Container name inside the ingestion task definition |
| `INGESTION_ECS_LAUNCH_TYPE` | `FARGATE` | ECS launch type for ingestion jobs |
| `INGESTION_ECS_PLATFORM_VERSION` | `LATEST` | ECS platform version for ingestion jobs |
| `INGESTION_ECS_ASSIGN_PUBLIC_IP` | `ENABLED` | Whether the task gets a public IP |
| `INGESTION_ECS_SUBNETS` | — | Comma-separated subnets for the ingestion task |
| `INGESTION_ECS_SECURITY_GROUPS` | — | Comma-separated security groups for the ingestion task |
| `INGESTION_JOBS_DATABASE_URL` | — | Optional Aurora/PostgreSQL URL for ingestion job tracking |
| `INGESTION_JOBS_CONNECT_TIMEOUT_SECONDS` | `5` | Connection timeout used by ingestion job registry updates |
| `RESTART_COMMAND` | — | Optional shell command to run when the admin presses restart |

The editable non-secret model routing settings live in `rag_eng/runtime_config.yaml`.
`openai`, `cohere`, `ollama`, `sagemaker`, and `bedrock` are all valid provider
choices in the admin UI. Bedrock uses Converse on `bedrock-runtime` and supports
models such as Amazon Nova 2 Lite and Anthropic Claude 3.5 Haiku.
