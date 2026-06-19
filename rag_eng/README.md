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
| `POST` | `/run/compile` | Compile + run student C++ code |
| `GET` | `/gradio` | Gradio RAG interrogation UI |
| `POST` | `/admin/index/ensure` | Idempotent index bootstrap |
| `POST` | `/admin/index/rebuild` | Destructive index rebuild |

## Local setup

1. Copy `.env.example` to `.env` at the repo root.
2. Fill in `QDRANT_URL`, `QDRANT_API_KEY`, `COHERE_API_KEY`, and Cognito variables.
3. Fill in `OPENAI_API_KEY` if you plan to route either chat or RAG through OpenAI.
4. Install dependencies:

```bash
uv sync
# or
pip install -r requirements.txt
```

5. If you have the Aurora course registry URL, verify the runtime lookup path:

```bash
export COURSE_REGISTRY_DATABASE_URL="postgresql://user:password@aurora-endpoint:5432/postgres?sslmode=require"
uv run python -m rag_eng.cli resolve-course --course-id mit-14
uv run python -m rag_eng.cli resolve-course --course-source cs50
```

The `/health` endpoint now reports whether the Aurora-backed course registry is configured and reachable when that env var is present.

6. Ensure or rebuild the index:

```bash
python -m rag_eng.cli ensure-index
```

7. Run the service on port 8001 (frontend default):

```bash
uv run uvicorn rag_eng.main:app --host 0.0.0.0 --port 8001
```

8. Open:
- API docs: `http://localhost:8001/docs`
- Gradio UI: `http://localhost:8001/gradio`

### Gradio diagnostics

The Gradio backend console now exposes retrieval tuning controls in the
Pipeline tab:

- `Retrieval Preset` for quick experiment-backed configurations
- `Top K / Final Results` for the final retrieved context size
- `Rerank Strategy` for `similarity` or MMR-based reranking
- routing / trace overrides for `course_id`, `session_id`, `request_id`,
  `turn_id`, and `section_id`

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
| `COURSE_REGISTRY_DATABASE_URL` | — | Optional Aurora/PostgreSQL URL for course registry lookups |
| `DATABASE_URL` | — | Generic Aurora/PostgreSQL fallback URL for course registry lookups |
| `RESTART_COMMAND` | — | Optional shell command to run when the admin presses restart |

The editable non-secret model routing settings live in `rag_eng/runtime_config.yaml`.
