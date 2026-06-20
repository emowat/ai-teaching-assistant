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

## Build

```bash
docker build -f ingestion_worker/Dockerfile -t codingrabbit-ingestion:dev .
```

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

