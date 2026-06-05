# `rag_eng`

`rag_eng` is the AWS-ready service layer for the capstone RAG pipeline.

## What it adds

- FastAPI query endpoint at `POST /query`
- Health endpoint at `GET /health`
- Idempotent index bootstrap at `POST /admin/index/ensure`
- Explicit destructive rebuild at `POST /admin/index/rebuild`
- CLI indexing commands:
  - `python -m rag_eng.cli ensure-index`
  - `python -m rag_eng.cli rebuild-index`
- Internal Gradio UI mounted at `/gradio`

## Local setup

1. Copy `.env.example` to `.env`
2. Fill in `QDRANT_URL`, `QDRANT_API_KEY`, and `COHERE_API_KEY`
3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Ensure or rebuild the index:

```bash
python -m rag_eng.cli ensure-index
```

5. Run the service:

```bash
uvicorn rag_eng.main:app --host 0.0.0.0 --port 8000
```

6. Open:

- API docs: `http://localhost:8000/docs`
- Gradio UI: `http://localhost:8000/gradio`

## Docker

Build and run with:

```bash
docker build -t rag-eng .
docker run --rm -p 8000:8000 --env-file .env rag-eng
```
