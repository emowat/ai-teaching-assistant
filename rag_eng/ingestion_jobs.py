"""ECS ingestion job launcher and Aurora job registry helpers."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping

from dotenv import load_dotenv

from rag.course_registry import get_course_registry
from rag_eng.schemas import IngestionJobLaunchRequest, IngestionJobResponse


load_dotenv()

logger = logging.getLogger(__name__)


def _format_timestamp(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _json_safe_value(value: object) -> object:
    """Recursively convert Python objects into JSON-serializable values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, set):
        return [_json_safe_value(item) for item in sorted(value, key=str)]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _json_adapter(data: dict[str, Any]) -> Any:
    """Adapt dictionaries to JSONB if psycopg is available."""
    try:
        from psycopg.types.json import Jsonb
    except ImportError:  # pragma: no cover - handled by the connection helper
        return data

    return Jsonb(_json_safe_value(data))


def _connect_postgres(database_url: str, connect_timeout_seconds: int):
    """Create a psycopg connection lazily so local tests do not need it imported."""
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - only when dependency missing
        raise RuntimeError("psycopg is required for ingestion job persistence.") from exc

    return psycopg.connect(database_url, connect_timeout=connect_timeout_seconds)


@dataclass(frozen=True)
class IngestionRuntimeConfig:
    """Runtime settings for the on-demand ECS ingestion launcher."""

    database_url: str | None
    ecs_cluster: str
    ecs_task_definition: str
    ecs_container_name: str
    ecs_launch_type: str
    ecs_platform_version: str
    ecs_assign_public_ip: str
    ecs_subnet_ids: tuple[str, ...]
    ecs_security_group_ids: tuple[str, ...]
    aws_region: str
    aws_profile: str | None
    connect_timeout_seconds: int


def _csv_values(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def load_ingestion_runtime_config(
    env: Mapping[str, str] | None = None,
) -> IngestionRuntimeConfig:
    """Load ECS ingestion settings from the process environment."""
    source = env or os.environ
    return IngestionRuntimeConfig(
        database_url=(
            source.get("INGESTION_JOBS_DATABASE_URL")
            or source.get("COURSE_REGISTRY_DATABASE_URL")
            or source.get("DATABASE_URL")
        ),
        ecs_cluster=source.get("INGESTION_ECS_CLUSTER", "").strip(),
        ecs_task_definition=source.get("INGESTION_ECS_TASK_DEFINITION", "").strip(),
        ecs_container_name=source.get(
            "INGESTION_ECS_CONTAINER_NAME",
            "ingestion-worker",
        ).strip(),
        ecs_launch_type=source.get("INGESTION_ECS_LAUNCH_TYPE", "FARGATE").strip(),
        ecs_platform_version=source.get(
            "INGESTION_ECS_PLATFORM_VERSION",
            "LATEST",
        ).strip(),
        ecs_assign_public_ip=source.get(
            "INGESTION_ECS_ASSIGN_PUBLIC_IP",
            "ENABLED",
        ).strip(),
        ecs_subnet_ids=_csv_values(source.get("INGESTION_ECS_SUBNETS")),
        ecs_security_group_ids=_csv_values(source.get("INGESTION_ECS_SECURITY_GROUPS")),
        aws_region=source.get(
            "AWS_REGION",
            source.get("AWS_DEFAULT_REGION", "us-east-1"),
        ).strip(),
        aws_profile=source.get("AWS_PROFILE") or None,
        connect_timeout_seconds=int(
            source.get("INGESTION_JOBS_CONNECT_TIMEOUT_SECONDS", "5")
        ),
    )


def _build_ecs_client(runtime: IngestionRuntimeConfig):
    import boto3

    session = boto3.Session(
        profile_name=runtime.aws_profile,
        region_name=runtime.aws_region,
    )
    return session.client("ecs")


def _resolve_course(course_id: str, collection_name: str | None) -> tuple[str, str]:
    route = get_course_registry().resolve(course_id=course_id)
    resolved_collection = collection_name or route.collection_name
    return route.course_id, resolved_collection


def build_ingestion_worker_command(
    request: IngestionJobLaunchRequest,
    *,
    course_id: str,
    collection_name: str,
) -> list[str]:
    """Build the ECS task command for the ingestion worker.

    The container image already sets the Python module entrypoint, so ECS only
    needs the subcommand plus its arguments here.
    """
    command = [
        request.job_kind,
        "--bucket",
        request.bucket,
        "--input-prefix",
        request.input_prefix,
        "--course-id",
        course_id,
    ]
    if request.job_kind == "parse":
        if request.output_prefix:
            command.extend(["--output-prefix", request.output_prefix])
        return command

    command.extend(["--collection-name", collection_name])
    if request.prepared_output_prefix:
        command.extend(["--prepared-output-prefix", request.prepared_output_prefix])
    if request.recreate_collection:
        command.append("--recreate-collection")
    return command


def build_ingestion_task_overrides(
    *,
    runtime: IngestionRuntimeConfig,
    request: IngestionJobLaunchRequest,
    job_id: str,
    course_corpus_version_id: str | None,
    course_id: str,
    collection_name: str,
) -> dict[str, Any]:
    """Build ECS container overrides for the ingestion worker task."""
    environment: list[dict[str, str]] = [
        {"name": "INGESTION_JOB_ID", "value": job_id},
        {"name": "INGESTION_JOB_KIND", "value": request.job_kind},
        {"name": "AWS_REGION", "value": runtime.aws_region},
    ]
    if course_corpus_version_id:
        environment.append(
            {"name": "COURSE_CORPUS_VERSION_ID", "value": course_corpus_version_id}
        )

    return {
        "containerOverrides": [
            {
                "name": runtime.ecs_container_name,
                "command": build_ingestion_worker_command(
                    request,
                    course_id=course_id,
                    collection_name=collection_name,
                ),
                "environment": environment,
            }
        ]
    }


def _ingestion_job_payload(
    *,
    request: IngestionJobLaunchRequest,
    course_id: str,
    collection_name: str,
    job_id: str,
    course_corpus_version_id: str | None,
) -> dict[str, Any]:
    payload = {
        "job_id": job_id,
        "course_id": course_id,
        "job_kind": request.job_kind,
        "bucket": request.bucket,
        "input_prefix": request.input_prefix,
        "output_prefix": request.output_prefix,
        "prepared_output_prefix": request.prepared_output_prefix,
        "collection_name": collection_name,
        "recreate_collection": request.recreate_collection,
    }
    if course_corpus_version_id:
        payload["course_corpus_version_id"] = course_corpus_version_id
    return payload


def _insert_job_rows(
    *,
    connection,
    request: IngestionJobLaunchRequest,
    runtime: IngestionRuntimeConfig,
    job_id: str,
    course_id: str,
    collection_name: str,
    course_corpus_version_id: str | None,
) -> None:
    with connection.cursor() as cursor:
        if course_corpus_version_id:
            cursor.execute(
                """
                INSERT INTO course_corpus_versions (
                  course_corpus_version_id,
                  course_id,
                  collection_name,
                  source_bucket,
                  source_prefix,
                  parsed_prefix,
                  prepared_prefix,
                  status,
                  active,
                  recreate_collection,
                  metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'queued', FALSE, %s, %s)
                """,
                (
                    course_corpus_version_id,
                    course_id,
                    collection_name,
                    request.bucket,
                    request.input_prefix,
                    request.output_prefix,
                    request.prepared_output_prefix,
                    request.recreate_collection,
                    _json_adapter(_ingestion_job_payload(
                        request=request,
                        course_id=course_id,
                        collection_name=collection_name,
                        job_id=job_id,
                        course_corpus_version_id=course_corpus_version_id,
                    )),
                ),
            )

        cursor.execute(
            """
            INSERT INTO ingestion_jobs (
              job_id,
              course_id,
              course_corpus_version_id,
              job_kind,
              status,
              message,
              bucket,
              input_prefix,
              output_prefix,
              prepared_output_prefix,
              collection_name,
              recreate_collection,
              ecs_cluster,
              ecs_task_definition,
              ecs_container_name,
              request_payload
            )
            VALUES (
              %s, %s, %s, %s, 'queued', '', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                job_id,
                course_id,
                course_corpus_version_id,
                request.job_kind,
                request.bucket,
                request.input_prefix,
                request.output_prefix,
                request.prepared_output_prefix,
                collection_name,
                request.recreate_collection,
                runtime.ecs_cluster,
                runtime.ecs_task_definition,
                runtime.ecs_container_name,
                _json_adapter(
                    _ingestion_job_payload(
                        request=request,
                        course_id=course_id,
                        collection_name=collection_name,
                        job_id=job_id,
                        course_corpus_version_id=course_corpus_version_id,
                    )
                ),
            ),
        )


def _update_job_status(
    *,
    connection,
    job_id: str,
    status: str,
    message: str,
    ecs_task_arn: str | None = None,
    ecs_response: dict[str, Any] | None = None,
    started: bool = False,
    completed: bool = False,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE ingestion_jobs
            SET
              status = %s,
              message = %s,
              ecs_task_arn = COALESCE(%s, ecs_task_arn),
              ecs_response = COALESCE(%s, ecs_response),
              started_at = CASE WHEN %s THEN COALESCE(started_at, now()) ELSE started_at END,
              completed_at = CASE WHEN %s THEN now() ELSE completed_at END,
              updated_at = now()
            WHERE job_id = %s
            """,
            (
                status,
                message,
                ecs_task_arn,
                _json_adapter(ecs_response or {}),
                started,
                completed,
                job_id,
            ),
        )


def _update_corpus_version_status(
    *,
    connection,
    course_corpus_version_id: str,
    status: str,
    active: bool,
    message: str,
    completed: bool = False,
    started: bool = False,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE course_corpus_versions
            SET
              status = %s,
              active = %s,
              metadata = COALESCE(metadata, '{}'::jsonb) || %s,
              started_at = CASE WHEN %s THEN COALESCE(started_at, now()) ELSE started_at END,
              completed_at = CASE WHEN %s THEN now() ELSE completed_at END,
              updated_at = now()
            WHERE course_corpus_version_id = %s
            """,
            (
                status,
                active,
                _json_adapter({"message": message}),
                started,
                completed,
                course_corpus_version_id,
            ),
        )


def _row_to_response(row: tuple[Any, ...]) -> IngestionJobResponse:
    (
        job_id,
        course_id,
        course_corpus_version_id,
        job_kind,
        status,
        message,
        ecs_cluster,
        ecs_task_definition,
        ecs_container_name,
        ecs_task_arn,
        collection_name,
        bucket,
        input_prefix,
        output_prefix,
        prepared_output_prefix,
        recreate_collection,
        request_payload,
        ecs_response,
        created_at,
        updated_at,
        started_at,
        completed_at,
    ) = row

    return IngestionJobResponse(
        job_id=str(job_id),
        course_id=str(course_id),
        job_kind=str(job_kind),
        status=str(status),
        message=str(message or ""),
        registered=True,
        course_corpus_version_id=(
            str(course_corpus_version_id) if course_corpus_version_id is not None else None
        ),
        ecs_cluster=str(ecs_cluster or ""),
        ecs_task_definition=str(ecs_task_definition or ""),
        ecs_container_name=str(ecs_container_name or ""),
        ecs_task_arn=str(ecs_task_arn) if ecs_task_arn is not None else None,
        collection_name=str(collection_name) if collection_name is not None else None,
        bucket=str(bucket or ""),
        input_prefix=str(input_prefix or ""),
        output_prefix=str(output_prefix) if output_prefix is not None else None,
        prepared_output_prefix=(
            str(prepared_output_prefix) if prepared_output_prefix is not None else None
        ),
        request_payload=dict(request_payload or {}),
        ecs_response=dict(ecs_response or {}),
        created_at=_format_timestamp(created_at),
        updated_at=_format_timestamp(updated_at),
        started_at=_format_timestamp(started_at) or None,
        completed_at=_format_timestamp(completed_at) or None,
    )


def _fetch_job_row(
    *,
    connection,
    job_id: str,
) -> tuple[Any, ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              job_id,
              course_id,
              course_corpus_version_id,
              job_kind,
              status,
              message,
              ecs_cluster,
              ecs_task_definition,
              ecs_container_name,
              ecs_task_arn,
              collection_name,
              bucket,
              input_prefix,
              output_prefix,
              prepared_output_prefix,
              recreate_collection,
              request_payload,
              ecs_response,
              created_at,
              updated_at,
              started_at,
              completed_at
            FROM ingestion_jobs
            WHERE job_id = %s
            """,
            (job_id,),
        )
        row = cursor.fetchone()
    if row is None:
        raise LookupError(f"Ingestion job not found: {job_id}")
    return row


def _ecs_run_task_response_to_dict(response: dict[str, Any]) -> dict[str, Any]:
    return {
        "tasks": response.get("tasks", []) or [],
        "failures": response.get("failures", []) or [],
    }


def launch_ingestion_job(
    request: IngestionJobLaunchRequest,
    *,
    runtime: IngestionRuntimeConfig | None = None,
    ecs_client=None,
) -> IngestionJobResponse:
    """Register an ingestion job and launch its ECS task."""
    runtime = runtime or load_ingestion_runtime_config()
    if not runtime.database_url:
        raise RuntimeError("Ingestion jobs database URL is not configured.")
    if not runtime.ecs_cluster or not runtime.ecs_task_definition:
        raise RuntimeError("ECS ingestion runtime is not configured.")
    if not runtime.ecs_subnet_ids or not runtime.ecs_security_group_ids:
        raise RuntimeError("ECS ingestion runtime requires subnets and security groups.")

    course_id, collection_name = _resolve_course(request.course_id, request.collection_name)
    job_id = uuid.uuid4().hex
    course_corpus_version_id = job_id if request.job_kind == "chunk-index" else None

    with _connect_postgres(
        runtime.database_url,
        runtime.connect_timeout_seconds,
    ) as connection:
        _insert_job_rows(
            connection=connection,
            request=request,
            runtime=runtime,
            job_id=job_id,
            course_id=course_id,
            collection_name=collection_name,
            course_corpus_version_id=course_corpus_version_id,
        )

    client = ecs_client or _build_ecs_client(runtime)
    task_overrides = build_ingestion_task_overrides(
        runtime=runtime,
        request=request,
        job_id=job_id,
        course_corpus_version_id=course_corpus_version_id,
        course_id=course_id,
        collection_name=collection_name,
    )
    run_task_kwargs = {
        "cluster": runtime.ecs_cluster,
        "taskDefinition": runtime.ecs_task_definition,
        "count": 1,
        "launchType": runtime.ecs_launch_type,
        "platformVersion": runtime.ecs_platform_version,
        "overrides": task_overrides,
    }
    if runtime.ecs_subnet_ids and runtime.ecs_security_group_ids:
        run_task_kwargs["networkConfiguration"] = {
            "awsvpcConfiguration": {
                "subnets": list(runtime.ecs_subnet_ids),
                "securityGroups": list(runtime.ecs_security_group_ids),
                "assignPublicIp": runtime.ecs_assign_public_ip,
            }
        }

    try:
        ecs_response = client.run_task(**run_task_kwargs)
        ecs_summary = _ecs_run_task_response_to_dict(ecs_response)
        failures = ecs_summary["failures"]
        task_arn = None
        tasks = ecs_summary["tasks"]
        if tasks and isinstance(tasks[0], dict):
            task_arn = tasks[0].get("taskArn")
            if task_arn is not None:
                task_arn = str(task_arn)
        launch_failed = bool(failures) or not task_arn

        with _connect_postgres(
            runtime.database_url,
            runtime.connect_timeout_seconds,
        ) as connection:
            if launch_failed:
                message = "ECS ingestion task launch failed."
                if failures:
                    message = f"ECS ingestion task launch failed: {failures}"
                _update_job_status(
                    connection=connection,
                    job_id=job_id,
                    status="launch_failed",
                    message=message,
                    ecs_response=ecs_summary,
                    completed=True,
                )
                if course_corpus_version_id:
                    _update_corpus_version_status(
                        connection=connection,
                        course_corpus_version_id=course_corpus_version_id,
                        status="failed",
                        active=False,
                        message=message,
                        completed=True,
                    )
            else:
                _update_job_status(
                    connection=connection,
                    job_id=job_id,
                    status="running",
                    message="ECS ingestion task launched.",
                    ecs_task_arn=task_arn,
                    ecs_response=ecs_summary,
                    started=True,
                )
                if course_corpus_version_id:
                    _update_corpus_version_status(
                        connection=connection,
                        course_corpus_version_id=course_corpus_version_id,
                        status="running",
                        active=False,
                        message="ECS ingestion task launched.",
                        started=True,
                    )
    except Exception as exc:
        with _connect_postgres(
            runtime.database_url,
            runtime.connect_timeout_seconds,
        ) as connection:
            message = f"ECS ingestion task launch failed: {exc}"
            _update_job_status(
                connection=connection,
                job_id=job_id,
                status="launch_failed",
                message=message,
                completed=True,
            )
            if course_corpus_version_id:
                _update_corpus_version_status(
                    connection=connection,
                    course_corpus_version_id=course_corpus_version_id,
                    status="failed",
                    active=False,
                    message=message,
                    completed=True,
                )

    with _connect_postgres(
        runtime.database_url,
        runtime.connect_timeout_seconds,
    ) as connection:
        return _row_to_response(_fetch_job_row(connection=connection, job_id=job_id))


def get_ingestion_job(
    job_id: str,
    *,
    runtime: IngestionRuntimeConfig | None = None,
) -> IngestionJobResponse:
    """Fetch a registered ingestion job by ID."""
    runtime = runtime or load_ingestion_runtime_config()
    if not runtime.database_url:
        raise RuntimeError("Ingestion jobs database URL is not configured.")

    with _connect_postgres(
        runtime.database_url,
        runtime.connect_timeout_seconds,
    ) as connection:
        return _row_to_response(_fetch_job_row(connection=connection, job_id=job_id))


def complete_ingestion_job(
    job_id: str,
    *,
    status: str,
    message: str = "",
    ecs_response: dict[str, Any] | None = None,
    runtime: IngestionRuntimeConfig | None = None,
) -> bool:
    """Mark an ingestion job complete and activate its corpus version if needed."""
    runtime = runtime or load_ingestion_runtime_config()
    if not runtime.database_url:
        logger.warning("Ingestion job completion skipped; database URL is missing.")
        return False

    try:
        with _connect_postgres(
            runtime.database_url,
            runtime.connect_timeout_seconds,
        ) as connection:
            row = _fetch_job_row(connection=connection, job_id=job_id)
            job_kind = str(row[3])
            course_corpus_version_id = (
                str(row[2]) if row[2] is not None else None
            )
            _update_job_status(
                connection=connection,
                job_id=job_id,
                status=status,
                message=message,
                ecs_response=ecs_response,
                completed=True,
            )
            if course_corpus_version_id:
                _update_corpus_version_status(
                    connection=connection,
                    course_corpus_version_id=course_corpus_version_id,
                    status=status,
                    active=(status == "completed" and job_kind == "chunk-index"),
                    message=message,
                    completed=True,
                )
        return True
    except Exception as exc:
        logger.warning(
            "Ingestion job completion skipped for %s: %s",
            job_id,
            exc,
        )
        return False
