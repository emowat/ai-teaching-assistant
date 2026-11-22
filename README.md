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
- `GET  /me` — authenticated profile + role
- `POST /query` — RAG query
- `POST /api/chat` — VS Code extension / full pipeline chat API
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

## Using the app

### Admin workflow

1. Sign in through the frontend at `http://localhost:5173`.
2. Open the Admin dashboard.
3. Create or edit courses in the `Courses` tab.
4. Upload source files and launch `parse` / `chunk-index` jobs from `RAG Docs`.
5. Use `AI Models` to change non-secret model routing.
6. Use `Backend Diagnostic Console` for input guardrail, retrieval, guardrail, and pipeline inspection.

### Student workflow

1. Sign in through the frontend.
2. Open the student dashboard.
3. Use chat for tutoring help and the C++ console for `POST /run/compile`.

### API and workflow references

- [rag_eng/README.md](/home/user/MIDS/w210/capstone/rag_eng/README.md) — backend setup, auth, endpoint inventory
- [docs/api_workflows.md](/home/user/MIDS/w210/capstone/docs/api_workflows.md) — detailed `curl` examples for runtime and admin workflows
- FastAPI OpenAPI docs: `http://localhost:8001/docs`

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
| `PLAYLAB_API_KEY` | Playlab org API key (server-side only; see below) |
| `PLAYLAB_PROJECT_ID` | Playlab app ID (last segment of the app's `/build/<id>` URL) |
| `PLAYLAB_API_BASE_URL` | Optional; defaults to `https://www.playlab.ai/api/v1` |
| `PLAYLAB_MAX_TURNS_PER_CONVERSATION` | Optional; turns before a fresh Playlab conversation (default 10) |

## Playlab integration (experimental)

Playlab can serve as the chat **generation** provider. Select it in the admin
dashboard (Chat provider → Playlab); switch back to Bedrock the same way.
Retrieval, guardrails, and telemetry stay in CodingRabbit.

- **Instructions live in the Playlab app**, not in our request. Keep the app's
  instructions in sync with `playlab/app_instructions.md` (generated from
  `rag_eng/prompts.py`; both modes in one app, selected by the `Mode:` line).
  Leave the app's reference library empty: our retrieval is week-aware, Playlab's is not.
- **Request flow per turn** (`rag_eng/playlab_generation.py`): look up the Playlab
  conversation for this user + extension `session_id` (Aurora table
  `playlab_conversations`, created on first use) and send only the current turn:
  `[Vector_Database_Results]` + the extension's context blocks + the student
  question. Playlab keeps the history and cannot trim it, so we start a fresh
  conversation on a new chat (extension history empty), a Homework/Study mode
  switch, or every `PLAYLAB_MAX_TURNS_PER_CONVERSATION` turns (default 10).
  A fresh conversation's first message is prefixed with the last 6 messages of
  our own history as `[Conversation_History]`, so context carries over.
  Fresh conversations cost ~4s extra to first token, so we don't start one every turn.
  `provider_metadata.new_conversation_reason` in the turn snapshot records why.
- **Session context** (week, syllabus limits, style rules, teaching plan) is also
  offered as the `session_context` instruction variable at creation, but Playlab
  only applies variables configured as starter inputs in the app, so in practice
  this context arrives in each message.
- **Streaming:** Playlab streams SSE (`event: append`, `data: {"delta": ...}`);
  the client re-emits the same NDJSON chunks as the Bedrock path, so the
  extension and mid-stream guardrails are unchanged.
- **Telemetry:** each generation attempt records `analysis_present` and the
  Playlab conversation ID. Playlab does not report token counts.
- Code-leakage retries are sent into the same Playlab conversation, so the
  rejected draft stays in Playlab's history (it is never shown to the student).

## Running tests

```bash
uv run pytest test/
```

## Architecture plans

Detailed phased implementation plans live in `local_docs/`:
- `codingrabbit_sandbox_aws_plan.md` — C++ sandbox AWS serverless roadmap (SQS, Fargate, Aurora, ElastiCache)
- `codingrabbit_monaco_sandbox_implementation.md` — Monaco editor integration notes
- `auth_mvp_minimal_path.md` — Cognito setup walkthrough
