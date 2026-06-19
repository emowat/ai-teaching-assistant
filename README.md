# codingrabbit.dev — AI Teaching Assistant

A full-stack AI-powered teaching assistant for CS courses with a Socratic tutoring chatbot, live C++ code execution sandbox, and role-based dashboards for admins, professors, and students.

## Repository layout

```
capstone/
├── frontend/          React + Vite + TypeScript UI
├── rag_eng/           FastAPI service (RAG pipeline, C++ runner API, Gradio UI)
├── runner/            Hardened Docker C++ sandbox image
├── rag/               Retrieval pipeline utilities
├── data_ingestion/    Document ingestion scripts (CS50x, C++ guidelines, …)
├── synthetic-transcripts/ Dataset generation for fine-tuning
├── test/              Backend Pytest suite
├── scripts/           Helper shell scripts
└── local_docs/        Architecture plans and ADRs
```

## Quick start (local development)

### Prerequisites

- Node 20+, `npm`
- Python 3.11+, [`uv`](https://github.com/astral-sh/uv)
- Docker (for the C++ sandbox runner)
- AWS Cognito user pool (see `local_docs/auth_mvp_minimal_path.md`)

### 1. Configure environment

```bash
cp .env.example .env
# Fill in QDRANT_URL, QDRANT_API_KEY, COHERE_API_KEY, Cognito vars
```

### 2. Build the C++ sandbox image

```bash
./scripts/build-runner.sh
```

### 3. Start the backend

```bash
uv run uvicorn rag_eng.main:app --host 0.0.0.0 --port 8001
```

Endpoints:
- `GET  /health` — liveness probe
- `POST /query` — RAG query
- `POST /run/compile` — C++ compile + run
- `GET  /gradio` — Gradio RAG interrogation UI
- `POST /admin/index/ensure` — idempotent index bootstrap

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

### Optional: start both together

If you want one shell to launch both dev servers, use:

```bash
./scripts/dev.sh
```

The script starts `rag_eng` on port `8001` and the Vite frontend on port `5173`.

## Role-based access

| Role      | Dashboards accessible          |
|-----------|-------------------------------|
| admin     | Admin, Professor, Student      |
| professor | Professor, Student             |
| student   | Student only                   |

Roles are derived from the Cognito JWT `custom:role` claim. The TopBar shows a switcher for all views the current user may access.

## C++ sandbox (Phase 1 — local Docker)

The student editor sends all workspace files to `POST /run/compile`. The backend:
1. Writes files to a temporary host directory.
2. Runs `docker run --network none --read-only … codingrabbit-cpp-runner:0.1` with strict resource limits (no network, 128 MB RAM, 1 CPU, 30 s timeout).
3. Returns `stdout`, `stderr`, exit code, and elapsed time to the frontend.

Set `RUNNER_MODE=subprocess` in `.env` to skip Docker and compile directly (development only, **not** safe for untrusted code).

## Key environment variables

| Variable | Description |
|---|---|
| `QDRANT_URL` | Qdrant Cloud cluster URL |
| `QDRANT_API_KEY` | Qdrant API key |
| `COHERE_API_KEY` | Cohere reranker key |
| `COGNITO_REGION` | AWS region of the Cognito user pool |
| `COGNITO_USER_POOL_ID` | Cognito user pool ID |
| `COGNITO_APP_CLIENT_ID` | Cognito app client ID |
| `VITE_COGNITO_DOMAIN` | Cognito hosted UI domain (`https://…auth.us-east-1.amazoncognito.com`) |
| `VITE_COGNITO_REDIRECT_URI` | OAuth callback URI (`http://localhost:5173/auth/callback`) |
| `VITE_COGNITO_LOGOUT_URI` | Post-logout redirect URI (`http://localhost:5173/logout`) |
| `VITE_API_BASE_URL` | Backend base URL seen by the browser |
| `RUNNER_MODE` | `docker` (default) or `subprocess` |
| `RUNNER_IMAGE` | Docker image tag for the C++ runner |
| `CORS_ORIGINS` | Comma-separated allowed origins for the backend |

## Running tests

```bash
uv run pytest test/
```

## Architecture plans

Detailed phased implementation plans live in `local_docs/`:
- `codingrabbit_sandbox_aws_plan.md` — C++ sandbox AWS serverless roadmap (SQS, Fargate, Aurora, ElastiCache)
- `codingrabbit_monaco_sandbox_implementation.md` — Monaco editor integration notes
- `auth_mvp_minimal_path.md` — Cognito setup walkthrough
