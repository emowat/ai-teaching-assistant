# AWS Ingestion Deployment Plan

This plan covers the on-demand ingestion worker deployment path for CodingRabbit.
It is separate from the tutor model deployment and focuses on:

- building and pushing the ingestion worker container
- registering the ECS Fargate task definition
- wiring secrets and runtime env values correctly
- applying the Aurora registry / job tables
- smoke-testing S3 parser and chunk/index jobs end to end

The ingestion worker already exists in repo code and is launched by the backend
through `POST /admin/ingestion/launch`.

## 1. What This Deployment Owns

The deployment path owns:

- `data_ingestion/ingestion_worker.py`
- `data_ingestion/chunking.py`
- `ingestion_worker/Dockerfile`
- `rag_eng/ingestion_jobs.py`
- `deploy/deploy_ingestion_worker.py`
- `deploy/scripts/deploy-ingestion-worker.sh`
- `deploy/scripts/deploy-aurora-course-registry.sh`

It does not own:

- the main tutor model endpoint
- guardrail checkpoint restore
- frontend builds
- local notebook-style experimentation

## 2. Required AWS Primitives

Before the first live launch, you need these AWS resources:

- an ECR repository for the ingestion worker image
- an ECS cluster for ingestion tasks
- an ECS task execution role
- an ECS task role
- a pair of VPC subnets for `awsvpc` networking
- a security group that allows the worker to reach:
  - S3
  - Aurora PostgreSQL
  - Qdrant
- Secrets Manager secrets for sensitive runtime values
- the Aurora schema / seed data applied by the course-registry script

Recommended MVP setup:

- dedicated ECS cluster for ingestion
- `FARGATE` launch type
- `awsvpc` network mode
- `1024` CPU and `2048` MiB memory to start

## 3. Deployment Scripts In `deploy/`

These are the scripts you should use for the ingestion deployment.

### 3.1 `deploy/scripts/deploy-aurora-course-registry.sh`

Purpose:
- apply the Aurora course registry schema
- seed or update canonical course routing rows

Why it matters:
- the ingestion launcher resolves `course_id -> collection_name` through the
  course registry
- the job tables live in the same Aurora cluster

Use it when:
- the Aurora schema is new
- the `courses` or `course_aliases` tables need to be updated
- the `ingestion_jobs` and `course_corpus_versions` tables must be present

### 3.2 `deploy/scripts/deploy-ingestion-worker.sh`

Purpose:
- describe the worker deployment config
- render the ECS task definition JSON
- render the backend `.env` fragment for `INGESTION_ECS_*`
- register the ECS task definition

Use it when:
- you have built and pushed the worker image
- you want to register a new task definition revision
- you need to copy the backend launch settings into `.env`

Required actions:

```bash
./deploy/scripts/deploy-ingestion-worker.sh describe
./deploy/scripts/deploy-ingestion-worker.sh render-task-definition
./deploy/scripts/deploy-ingestion-worker.sh render-backend-env
./deploy/scripts/deploy-ingestion-worker.sh register-task-definition
```

### 3.3 Shared helper: `deploy/scripts/_load_deploy_config.sh`

This is not a user-facing command, but it is important because the deployment
scripts source it to load `.env` and `deploy/deployment.yaml`.

### 3.4 Not required for ingestion deployment

These scripts exist in `deploy/` but are not required for the ingestion worker:

- `prepare-custom-model-from-google-drive.sh`
- `deploy-custom-model-to-sagemaker-ai.sh`
- `restore-guardrail-checkpoint.sh`

## 4. Build And Push The Worker Image

The ingestion image is built from:

- `ingestion_worker/Dockerfile`

Build from the repo root:

```bash
docker build -f ingestion_worker/Dockerfile -t codingrabbit-ingestion:latest .
```

Tag for ECR:

```bash
docker tag codingrabbit-ingestion:latest \
  <account>.dkr.ecr.us-east-1.amazonaws.com/codingrabbit-ingestion:latest
```

Push:

```bash
docker push <account>.dkr.ecr.us-east-1.amazonaws.com/codingrabbit-ingestion:latest
```

The task definition should reference the ECR image URI, not a local image tag.

## 5. ECS Task Definition Inputs

The task definition is rendered by `deploy-ingestion-worker.sh` and registered
through ECS. The important inputs are:

- `INGESTION_ECS_IMAGE_URI`
- `INGESTION_ECS_EXECUTION_ROLE_ARN`
- `INGESTION_ECS_TASK_ROLE_ARN`
- `INGESTION_ECS_TASK_FAMILY`
- `INGESTION_ECS_TASK_DEFINITION`
- `INGESTION_ECS_CONTAINER_NAME`
- `INGESTION_ECS_CPU`
- `INGESTION_ECS_MEMORY`
- `INGESTION_ECS_LOG_GROUP`
- `INGESTION_ECS_LOG_STREAM_PREFIX`

The worker task definition also includes these runtime env values:

- `AWS_REGION`
- `AWS_DEFAULT_REGION`
- `QDRANT_URL`
- `EMBEDDING_MODEL`
- `QDRANT_COLLECTION_MIT13`
- `QDRANT_COLLECTION_MIT14`
- `QDRANT_COLLECTION_CS50`
- `QDRANT_COLLECTION_GUIDELINES`
- `INGESTION_JOBS_CONNECT_TIMEOUT_SECONDS`

The collection env vars are fallback defaults for local or bootstrap runs.
For live ingestion jobs, the backend resolves `course_id` through the registry
and passes `--collection-name` explicitly to the worker.

## 6. Secrets Mapping

Do not bake these into the image and do not pass them on the API request.
Map them through Secrets Manager instead.

Recommended secret keys:

- `INGESTION_JOBS_DATABASE_URL`
- `COURSE_REGISTRY_DATABASE_URL`
- `QDRANT_API_KEY`

The deploy helper expects them through:

```bash
INGESTION_ECS_SECRET_ARNS_JSON='{
  "INGESTION_JOBS_DATABASE_URL":"arn:aws:secretsmanager:...",
  "COURSE_REGISTRY_DATABASE_URL":"arn:aws:secretsmanager:...",
  "QDRANT_API_KEY":"arn:aws:secretsmanager:..."
}'
```

## 7. Backend `.env` Values

These are the values the backend uses to launch ECS tasks.

Required launcher values:

- `AWS_REGION`
- `AWS_PROFILE`
- `INGESTION_ECS_CLUSTER`
- `INGESTION_ECS_TASK_DEFINITION`
- `INGESTION_ECS_CONTAINER_NAME`
- `INGESTION_ECS_LAUNCH_TYPE`
- `INGESTION_ECS_PLATFORM_VERSION`
- `INGESTION_ECS_ASSIGN_PUBLIC_IP`
- `INGESTION_ECS_SUBNETS`
- `INGESTION_ECS_SECURITY_GROUPS`

Database values used by the launcher:

- `INGESTION_JOBS_DATABASE_URL`
  or
- `COURSE_REGISTRY_DATABASE_URL`

The repo-root [.env.example](/home/user/MIDS/w210/capstone/.env.example) includes
a ready-to-copy ingestion worker block with the launcher keys, task-definition
keys, and secret mapping placeholders in one place.

You can print the backend fragment with:

```bash
./deploy/scripts/deploy-ingestion-worker.sh render-backend-env
```

## 8. Full Deployment Order

### Step 1: Validate the local worker first

Confirm the image builds and the parser / chunker work locally.

Useful checks:

```bash
docker build -f ingestion_worker/Dockerfile -t codingrabbit-ingestion:latest .
docker run --rm codingrabbit-ingestion:latest --help
docker run --rm codingrabbit-ingestion:latest parse --help
docker run --rm codingrabbit-ingestion:latest chunk-index --help
```

### Step 2: Prepare AWS account access

Make sure the AWS profile works:

```bash
aws sts get-caller-identity --profile codingrabbit-dev
```

If the session expired, refresh it:

```bash
aws sso login --profile codingrabbit-dev
```

### Step 3: Create or confirm the ECR repository

Create the ECR repository if needed, then log in and push the image.

### Step 4: Apply the Aurora registry schema

Use the Aurora helper to make sure the registry tables and ingestion tables are
present:

```bash
./deploy/scripts/deploy-aurora-course-registry.sh apply \
  --resource-arn arn:aws:rds:... \
  --secret-arn arn:aws:secretsmanager:... \
  --database postgres \
  --region us-east-1 \
  --profile codingrabbit-dev
```

Then verify the registry:

```bash
./deploy/scripts/deploy-aurora-course-registry.sh verify \
  --resource-arn arn:aws:rds:... \
  --secret-arn arn:aws:secretsmanager:... \
  --database postgres \
  --region us-east-1 \
  --profile codingrabbit-dev
```

### Step 5: Register the ECS task definition

Fill in the required env vars and register the task definition:

```bash
./deploy/scripts/deploy-ingestion-worker.sh describe
./deploy/scripts/deploy-ingestion-worker.sh render-task-definition
./deploy/scripts/deploy-ingestion-worker.sh register-task-definition
```

### Step 6: Copy the backend launcher env values

Render the backend fragment and paste it into `.env`:

```bash
./deploy/scripts/deploy-ingestion-worker.sh render-backend-env
```

### Step 7: Launch a parser smoke test

Use the temporary S3 prefix created for smoke testing:

- `test-ingestion/teacher_uploads/mit14/`
- `test-ingestion/teacher_uploads/cppcore/`

Start with `parse` and confirm the JSON lands under:

- `test-ingestion/parsed_json/mit14/`
- `test-ingestion/parsed_json/cppcore/`

### Step 8: Launch a chunk/index smoke test

Point the worker at the parsed S3 prefix and confirm:

- prepared chunk artifacts are written
- Qdrant accepts the upsert
- Aurora moves the job to `completed`
- the corpus version becomes active for `chunk-index`

### Step 9: Clean up test S3 prefixes

Delete the temporary `test-ingestion/` objects after the smoke tests finish.

## 9. Recommended Job Payloads

Parser job:

```json
{
  "course_id": "mit14",
  "job_kind": "parse",
  "bucket": "codingrabbit-data-dev",
  "input_prefix": "test-ingestion/teacher_uploads/mit14/",
  "output_prefix": "test-ingestion/parsed_json/mit14/"
}
```

Chunk/index job:

```json
{
  "course_id": "mit14",
  "job_kind": "chunk-index",
  "bucket": "codingrabbit-data-dev",
  "input_prefix": "test-ingestion/parsed_json/mit14/",
  "prepared_output_prefix": "test-ingestion/prepared_chunks/mit14/",
  "recreate_collection": true
}
```

## 10. Acceptance Criteria

The deployment is ready when all of these are true:

- the worker image builds locally
- the image is pushed to ECR
- the ECS task definition registers successfully
- the backend launcher env values are copied into `.env`
- `POST /admin/ingestion/launch` starts a `parse` task
- the parser writes parsed JSON to S3
- `POST /admin/ingestion/launch` starts a `chunk-index` task
- the worker writes prepared chunk artifacts
- the worker updates job status in Aurora
- the corpus version becomes active after indexing completes

## 11. Notes For Future Courses

The current worker has fallback collection env vars for the known courses:

- `QDRANT_COLLECTION_MIT13`
- `QDRANT_COLLECTION_MIT14`
- `QDRANT_COLLECTION_CS50`
- `QDRANT_COLLECTION_GUIDELINES`

For new courses, the intended long-term path is:

1. add the course in Aurora
2. resolve `course_id -> collection_name` through the registry
3. pass `--collection-name` to the worker
4. keep the env vars as fallback defaults, not the source of truth
