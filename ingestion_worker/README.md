# Ingestion Worker Container

This folder packages the on-demand ECS Fargate worker for teacher-upload
ingestion. The Python logic lives in `data_ingestion/`; this folder only holds
the container packaging.

## What the worker does

- `parse`:
  - reads teacher uploads from S3 or a local folder
  - writes normalized JSON envelopes to `parsed_json/<course_id>/...`
- `chunk-index`:
  - reads parsed envelopes from S3 or a local folder
  - chunks them into Qdrant-ready payloads
  - embeds them
  - upserts them into Qdrant
  - optionally writes prepared chunk artifacts to S3 or local disk
  - marks the Aurora job row complete when `INGESTION_JOB_ID` is present

## Build

```bash
docker build -f ingestion_worker/Dockerfile -t codingrabbit-ingestion:dev .
```

## ECS wiring helper

Use the repo-side helper to describe or register the ECS task definition:

```bash
./deploy/scripts/deploy-ingestion-worker.sh describe
./deploy/scripts/deploy-ingestion-worker.sh render-task-definition
./deploy/scripts/deploy-ingestion-worker.sh render-backend-env
./deploy/scripts/deploy-ingestion-worker.sh register-task-definition
```

The helper expects the worker image URI, IAM role ARNs, and ECS subnet/security
group settings to be provided through `INGESTION_ECS_*` environment variables.
See [deploy/README.md](/home/user/MIDS/w210/capstone/deploy/README.md) for the
full wiring checklist and secret ARN mapping format.

The worker image installs the parser dependencies from `requirements.txt`, so
the container can parse PDFs, DOCX, PPTX, HTML, TXT, and Markdown files in the
same build.

## Run locally

Parse mode:

```bash
docker run --rm \
  -v "$PWD:/app" \
  codingrabbit-ingestion:dev \
  parse \
  --local-input-dir sample_teacher_uploads \
  --local-output-dir sample_parsed_json
```

Chunk/index mode:

```bash
docker run --rm \
  -v "$PWD:/app" \
  -e QDRANT_URL=http://localhost:6333 \
  -e QDRANT_API_KEY= \
  -e EMBEDDING_MODEL=sentence-transformers/multi-qa-mpnet-base-dot-v1 \
  codingrabbit-ingestion:dev \
  chunk-index \
  --local-input-dir sample_parsed_json \
  --local-output-dir sample_prepared_chunks \
  --collection-name mit14_course
```

## Runtime environment

The ECS task definition should inject runtime values, not bake them into the
image:

- `INGESTION_JOB_ID`
- `INGESTION_JOB_KIND`
- `INGESTION_JOBS_DATABASE_URL` or `COURSE_REGISTRY_DATABASE_URL`
- `AWS_REGION`
- `AWS_PROFILE` for local runs only
- `QDRANT_URL`
- `QDRANT_API_KEY`
- `EMBEDDING_MODEL`
- `QDRANT_COLLECTION_MIT13`
- `QDRANT_COLLECTION_MIT14`
- `QDRANT_COLLECTION_CS50`

For S3 mode, pass:

- `--bucket`
- `--input-prefix`
- optional `--prepared-output-prefix`
- optional `--course-id`

## Worker lifecycle

When the worker runs under ECS, the task definition should also set:

- `INGESTION_ECS_CLUSTER`
- `INGESTION_ECS_TASK_DEFINITION`
- `INGESTION_ECS_CONTAINER_NAME`
- `INGESTION_ECS_SUBNETS`
- `INGESTION_ECS_SECURITY_GROUPS`

The backend launches the task, writes the initial `ingestion_jobs` row, and
the worker updates the job and corpus-version rows on success or failure.
