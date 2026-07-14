"""Offline evaluation launch helpers and Aurora run registry accessors."""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

from deploy.deployment_config import load_deploy_config
from rag_eng.aurora_retry import connect_postgres_with_retry
from rag_eng.auth.models import CurrentUser
from rag_eng.app_registry import sync_application_user
from rag_eng.schemas import (
    EvaluationRunArtifact,
    EvaluationRunCreate,
    EvaluationRunMetric,
    EvaluationRunScope,
    EvaluationRunSummary,
)

load_dotenv()

logger = logging.getLogger(__name__)


def _format_timestamp(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _clean_text(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _json_safe_value(value: object) -> object:
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
    try:
        from psycopg.types.json import Jsonb
    except ImportError:  # pragma: no cover - psycopg is available in production
        return data

    return Jsonb(_json_safe_value(data))


def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _build_jsonl(records: list[dict[str, Any]]) -> str:
    return "\n".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True)
        for record in records
    ) + ("\n" if records else "")


def _build_s3_client(*, region: str, profile_name: str | None):
    session = boto3.Session(profile_name=profile_name, region_name=region)
    return session.client("s3")


def _build_ecs_client(*, region: str, profile_name: str | None):
    session = boto3.Session(profile_name=profile_name, region_name=region)
    return session.client("ecs")


def _build_logs_client(*, region: str, profile_name: str | None):
    session = boto3.Session(profile_name=profile_name, region_name=region)
    return session.client("logs")


def _ensure_log_group(client, *, log_group_name: str) -> None:
    try:
        client.create_log_group(logGroupName=log_group_name)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code != "ResourceAlreadyExistsException":
            raise


def _normalize_snapshot(snapshot: Any) -> dict[str, Any]:
    if isinstance(snapshot, dict):
        return dict(snapshot)
    if isinstance(snapshot, (bytes, bytearray, memoryview)):
        snapshot = bytes(snapshot).decode("utf-8")
    if isinstance(snapshot, str):
        parsed = json.loads(snapshot)
        if isinstance(parsed, dict):
            return parsed
    raise TypeError(f"Unsupported snapshot payload type: {type(snapshot)!r}")


def _coerce_utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class EvaluationLaunchRuntimeConfig:
    """Resolved runtime settings for launching offline evaluation runs."""

    database_url: str | None
    connect_timeout_seconds: int
    aws_region: str
    aws_profile: str | None
    ecs_cluster: str
    ecs_task_definition: str
    ecs_container_name: str
    ecs_log_group: str
    ecs_launch_type: str
    ecs_platform_version: str
    ecs_assign_public_ip: str
    ecs_subnet_ids: tuple[str, ...]
    ecs_security_group_ids: tuple[str, ...]
    results_bucket: str
    results_prefix: str
    default_judge_provider: str
    default_judge_model: str
    export_timezone: str


def _csv_values(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def load_evaluation_launch_runtime_config(
    env: Mapping[str, str] | None = None,
) -> EvaluationLaunchRuntimeConfig:
    """Load launch settings from deployment.yaml plus environment overrides."""

    source = env or os.environ
    deploy_config = load_deploy_config()
    worker = deploy_config.evaluation_worker
    worker_env = worker.environment

    return EvaluationLaunchRuntimeConfig(
        database_url=(
            source.get("COURSE_REGISTRY_DATABASE_URL")
            or source.get("DATABASE_URL")
        ),
        connect_timeout_seconds=int(
            source.get("EVALUATION_LAUNCH_CONNECT_TIMEOUT_SECONDS", "5")
        ),
        aws_region=source.get("AWS_REGION", deploy_config.aws.region).strip(),
        aws_profile=source.get("AWS_PROFILE") or deploy_config.aws.profile,
        ecs_cluster=worker.cluster,
        ecs_task_definition=worker.task_definition,
        ecs_container_name=worker.container_name,
        ecs_log_group=worker.log_group,
        ecs_launch_type=worker.launch_type,
        ecs_platform_version=worker.platform_version,
        ecs_assign_public_ip=worker.assign_public_ip,
        ecs_subnet_ids=tuple(worker.subnet_ids),
        ecs_security_group_ids=tuple(worker.security_group_ids),
        results_bucket=worker_env.get("S3_DATA_BUCKET", deploy_config.aws.s3_bucket),
        results_prefix=worker_env.get("EVALUATION_RESULTS_PREFIX", "evaluation/offline"),
        default_judge_provider=worker_env.get(
            "EVALUATION_DEFAULT_JUDGE_PROVIDER", "bedrock"
        ),
        default_judge_model=worker_env.get(
            "EVALUATION_DEFAULT_JUDGE_MODEL",
            "anthropic.claude-haiku-4-5",
        ),
        export_timezone=worker_env.get("EVALUATION_EXPORT_TZ", "America/Los_Angeles"),
    )


def get_evaluation_config_payload(
    *,
    runtime: EvaluationLaunchRuntimeConfig | None = None,
) -> dict[str, Any]:
    """Return the launch defaults consumed by the admin UI."""

    runtime = runtime or load_evaluation_launch_runtime_config()
    return {
        "default_judge_provider": runtime.default_judge_provider,
        "default_judge_model": runtime.default_judge_model,
        "supported_judge_providers": ["openai", "bedrock"],
        "results_bucket": runtime.results_bucket,
        "results_prefix": runtime.results_prefix,
        "export_timezone": runtime.export_timezone,
        "ecs": {
            "cluster": runtime.ecs_cluster,
            "task_definition": runtime.ecs_task_definition,
            "container_name": runtime.ecs_container_name,
            "launch_type": runtime.ecs_launch_type,
            "platform_version": runtime.ecs_platform_version,
            "assign_public_ip": runtime.ecs_assign_public_ip,
            "subnet_ids": list(runtime.ecs_subnet_ids),
            "security_group_ids": list(runtime.ecs_security_group_ids),
        },
    }


def _query_turn_snapshots(
    database_url: str,
    *,
    start_at: datetime,
    end_at: datetime,
    course_id: str | None = None,
    section_id: str | None = None,
    connect_timeout_seconds: int = 5,
) -> list[tuple[datetime, dict[str, Any]]]:
    sql = [
        """
        SELECT
          created_at,
          snapshot
        FROM tutor_turn_snapshots
        WHERE created_at >= %s
          AND created_at < %s
        """,
    ]
    params: list[Any] = [start_at, end_at]

    if course_id is not None:
        sql.append("AND course_id = %s")
        params.append(course_id)
    if section_id is not None:
        sql.append("AND section_id = %s")
        params.append(section_id)

    sql.append("ORDER BY created_at ASC, session_id ASC, turn_index ASC, turn_id ASC")
    query = "\n".join(sql)

    with connect_postgres_with_retry(
        database_url,
        profile="reliable",
        connect_timeout_seconds=connect_timeout_seconds,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()

    normalized: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        created_at = row[0] if isinstance(row, tuple) else row["created_at"]
        snapshot = row[1] if isinstance(row, tuple) else row["snapshot"]
        normalized.append(
            (_coerce_utc_datetime(created_at), _normalize_snapshot(snapshot))
        )
    return normalized


def export_turn_snapshots_to_s3(
    *,
    database_url: str,
    bucket: str,
    prefix: str,
    start_date: date | None = None,
    end_date: date | None = None,
    course_id: str | None = None,
    section_id: str | None = None,
    profile: str | None = None,
    region: str | None = None,
    connect_timeout_seconds: int = 5,
    tz: str = "America/Los_Angeles",
) -> dict[str, Any]:
    """Export filtered turn snapshots to a single JSONL object in S3."""

    import pytz

    pt_tz = pytz.timezone(tz)
    if start_date is None:
        start_date = datetime.now(pt_tz).date()
    if end_date is None:
        end_date = start_date
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    start_at = datetime.combine(start_date, time.min, tzinfo=pt_tz)
    end_at = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=pt_tz)

    rows = _query_turn_snapshots(
        database_url,
        start_at=start_at,
        end_at=end_at,
        course_id=course_id,
        section_id=section_id,
        connect_timeout_seconds=connect_timeout_seconds,
    )
    if not rows:
        raise RuntimeError("No evaluation rows were found for the requested scope.")

    records = [snapshot for _created_at, snapshot in rows]
    normalized_prefix = prefix.strip("/")
    dataset_key = f"{normalized_prefix}/turn_snapshots.jsonl"
    manifest_key = f"{normalized_prefix}/manifest.json"

    client = _build_s3_client(region=region or "us-east-1", profile_name=profile)
    client.put_object(
        Bucket=bucket,
        Key=dataset_key,
        Body=_build_jsonl(records).encode("utf-8"),
        ContentType="application/x-ndjson",
    )

    manifest = {
        "source_kind": "aurora-turn-snapshots",
        "source_uri": f"s3://{bucket}/{dataset_key}",
        "source_items": [f"s3://{bucket}/{dataset_key}"],
        "total_rows": len(records),
        "usable_rows": len(records),
        "skipped_rows": 0,
        "course_id": course_id,
        "section_id": section_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
    client.put_object(
        Bucket=bucket,
        Key=manifest_key,
        Body=json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
        ContentType="application/json",
    )

    return {
        "bucket": bucket,
        "prefix": normalized_prefix,
        "dataset_s3_uri": f"s3://{bucket}/{dataset_key}",
        "manifest_s3_uri": f"s3://{bucket}/{manifest_key}",
        "manifest": manifest,
    }


def _resolve_results_object_prefix(
    runtime: EvaluationLaunchRuntimeConfig,
    run_id: str,
) -> str:
    base_prefix = runtime.results_prefix.strip("/")
    return f"{base_prefix}/{run_id}" if base_prefix else run_id


def _resolve_results_root_prefix(runtime: EvaluationLaunchRuntimeConfig, run_id: str) -> str:
    return f"s3://{runtime.results_bucket}/{_resolve_results_object_prefix(runtime, run_id)}"


def _resolve_requestor(
    current_user: CurrentUser | None,
) -> dict[str, Any]:
    requestor = {
        "requested_by_user_id": None,
        "requested_by_cognito_sub": "",
        "requested_by_email": "",
    }
    if current_user is None:
        return requestor

    requestor["requested_by_cognito_sub"] = _clean_text(current_user.cognito_sub)
    requestor["requested_by_email"] = _clean_text(current_user.email)

    try:
        app_user = sync_application_user(current_user)
    except Exception as exc:  # pragma: no cover - best effort resolution
        logger.info("Evaluation requestor app-user sync skipped: %s", exc)
        return requestor

    if app_user:
        requestor["requested_by_user_id"] = app_user["user_id"]
    return requestor


def _build_worker_command(
    *,
    request: EvaluationRunCreate,
    run_id: str,
    dataset_s3_uri: str,
    results_s3_prefix: str,
    aws_region: str,
    requestor: dict[str, Any],
) -> list[str]:
    command = [
        "python",
        "-m",
        "model_eval.evaluation_worker",
        "--evaluation-run-id",
        run_id,
        "--judge-provider",
        request.judge_provider,
        "--judge-model",
        request.judge_model,
        "--dataset-s3-uri",
        dataset_s3_uri,
        "--results-s3-prefix",
        results_s3_prefix,
        "--aws-region",
        aws_region,
    ]

    optional_arguments: list[tuple[str, str | None]] = [
        ("--run-label", request.run_label or None),
        ("--notes", request.notes or None),
        ("--course-id", request.export_scope.course_id if request.export_scope else None),
        ("--section-id", request.export_scope.section_id if request.export_scope else None),
        ("--scope-start-date", request.export_scope.start_date if request.export_scope else None),
        ("--scope-end-date", request.export_scope.end_date if request.export_scope else None),
    ]
    if request.export_scope is not None:
        optional_arguments.append(
            ("--scope-metadata-json", json.dumps(request.export_scope.model_dump()))
        )

    for flag, value in optional_arguments:
        if value:
            command.extend([flag, value])

    return command


def _build_worker_overrides(
    *,
    runtime: EvaluationLaunchRuntimeConfig,
    request: EvaluationRunCreate,
    run_id: str,
    dataset_s3_uri: str,
    results_s3_prefix: str,
    requestor: dict[str, Any],
) -> dict[str, Any]:
    environment: list[dict[str, str]] = [
        {"name": "AWS_REGION", "value": runtime.aws_region},
        {"name": "EVALUATION_RUN_ID", "value": run_id},
        {"name": "EVALUATION_DATASET_S3_URI", "value": dataset_s3_uri},
        {"name": "EVALUATION_RESULTS_PREFIX", "value": results_s3_prefix},
    ]

    for key, value in requestor.items():
        if value:
            environment.append(
                {"name": f"EVALUATION_{key.upper()}", "value": str(value)}
            )

    if request.run_label:
        environment.append({"name": "EVALUATION_RUN_LABEL", "value": request.run_label})
    if request.notes:
        environment.append({"name": "EVALUATION_RUN_NOTES", "value": request.notes})
    if request.export_scope and request.export_scope.course_id:
        environment.append(
            {"name": "EVALUATION_COURSE_ID", "value": request.export_scope.course_id}
        )
    if request.export_scope and request.export_scope.section_id:
        environment.append(
            {"name": "EVALUATION_SECTION_ID", "value": request.export_scope.section_id}
        )
    if request.export_scope and request.export_scope.start_date:
        environment.append(
            {
                "name": "EVALUATION_SCOPE_START_DATE",
                "value": request.export_scope.start_date,
            }
        )
    if request.export_scope and request.export_scope.end_date:
        environment.append(
            {
                "name": "EVALUATION_SCOPE_END_DATE",
                "value": request.export_scope.end_date,
            }
        )
    if request.export_scope:
        environment.append(
            {
                "name": "EVALUATION_SCOPE_METADATA_JSON",
                "value": json.dumps(request.export_scope.model_dump(), sort_keys=True),
            }
        )

    return {
        "containerOverrides": [
            {
                "name": runtime.ecs_container_name,
                "command": _build_worker_command(
                    request=request,
                    run_id=run_id,
                    dataset_s3_uri=dataset_s3_uri,
                    results_s3_prefix=results_s3_prefix,
                    aws_region=runtime.aws_region,
                    requestor=requestor,
                ),
                "environment": environment,
            }
        ]
    }


def _run_task_response_to_dict(response: dict[str, Any]) -> dict[str, Any]:
    return {
        "tasks": response.get("tasks", []) or [],
        "failures": response.get("failures", []) or [],
    }


def _insert_run_row(
    *,
    connection,
    request: EvaluationRunCreate,
    requestor: dict[str, Any],
    run_id: str,
    dataset_s3_uri: str,
    results_s3_prefix: str,
    ecs_cluster: str,
    ecs_task_definition: str,
    ecs_container_name: str,
    scope_metadata: dict[str, Any],
    course_id: str | None,
    section_id: str | None,
    status: str = "queued",
    message: str = "",
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO evaluation_runs (
              evaluation_run_id,
              run_label,
              notes,
              requested_by_user_id,
              requested_by_cognito_sub,
              requested_by_email,
              judge_provider,
              judge_model,
              input_dataset_s3_uri,
              results_s3_prefix,
              course_id,
              section_id,
              scope_start_date,
              scope_end_date,
              scope_metadata,
              status,
              message,
              ecs_cluster,
              ecs_task_definition,
              ecs_container_name,
              request_payload
            )
            VALUES (
              %(evaluation_run_id)s,
              %(run_label)s,
              %(notes)s,
              %(requested_by_user_id)s,
              %(requested_by_cognito_sub)s,
              %(requested_by_email)s,
              %(judge_provider)s,
              %(judge_model)s,
              %(input_dataset_s3_uri)s,
              %(results_s3_prefix)s,
              %(course_id)s,
              %(section_id)s,
              %(scope_start_date)s,
              %(scope_end_date)s,
              %(scope_metadata)s,
              %(status)s,
              %(message)s,
              %(ecs_cluster)s,
              %(ecs_task_definition)s,
              %(ecs_container_name)s,
              %(request_payload)s
            )
            ON CONFLICT (evaluation_run_id) DO UPDATE SET
              run_label = EXCLUDED.run_label,
              notes = EXCLUDED.notes,
              requested_by_user_id = EXCLUDED.requested_by_user_id,
              requested_by_cognito_sub = EXCLUDED.requested_by_cognito_sub,
              requested_by_email = EXCLUDED.requested_by_email,
              judge_provider = EXCLUDED.judge_provider,
              judge_model = EXCLUDED.judge_model,
              input_dataset_s3_uri = EXCLUDED.input_dataset_s3_uri,
              results_s3_prefix = EXCLUDED.results_s3_prefix,
              course_id = EXCLUDED.course_id,
              section_id = EXCLUDED.section_id,
              scope_start_date = EXCLUDED.scope_start_date,
              scope_end_date = EXCLUDED.scope_end_date,
              scope_metadata = EXCLUDED.scope_metadata,
              status = EXCLUDED.status,
              message = EXCLUDED.message,
              ecs_cluster = EXCLUDED.ecs_cluster,
              ecs_task_definition = EXCLUDED.ecs_task_definition,
              ecs_container_name = EXCLUDED.ecs_container_name,
              request_payload = EXCLUDED.request_payload,
              updated_at = now()
            """,
            {
                "evaluation_run_id": run_id,
                "run_label": request.run_label,
                "notes": request.notes,
                "requested_by_user_id": requestor["requested_by_user_id"],
                "requested_by_cognito_sub": requestor["requested_by_cognito_sub"],
                "requested_by_email": requestor["requested_by_email"],
                "judge_provider": request.judge_provider,
                "judge_model": request.judge_model,
                "input_dataset_s3_uri": dataset_s3_uri,
                "results_s3_prefix": results_s3_prefix,
                "course_id": course_id,
                "section_id": section_id,
                "scope_start_date": request.export_scope.start_date if request.export_scope else None,
                "scope_end_date": request.export_scope.end_date if request.export_scope else None,
                "scope_metadata": _json_adapter(scope_metadata),
                "status": status,
                "message": message,
                "ecs_cluster": ecs_cluster,
                "ecs_task_definition": ecs_task_definition,
                "ecs_container_name": ecs_container_name,
                "request_payload": _json_adapter(
                    {
                        "request": request.model_dump(mode="json"),
                        "dataset_s3_uri": dataset_s3_uri,
                        "results_s3_prefix": results_s3_prefix,
                        "requested_by": requestor,
                        "scope_metadata": scope_metadata,
                    }
                ),
            },
        )


def _update_run_status(
    *,
    connection,
    run_id: str,
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
            UPDATE evaluation_runs
            SET
              status = %s,
              message = %s,
              ecs_task_arn = COALESCE(%s, ecs_task_arn),
              ecs_response = COALESCE(%s, ecs_response),
              started_at = CASE WHEN %s THEN COALESCE(started_at, now()) ELSE started_at END,
              completed_at = CASE WHEN %s THEN now() ELSE completed_at END,
              updated_at = now()
            WHERE evaluation_run_id = %s
            """,
            (
                status,
                message,
                ecs_task_arn,
                _json_adapter(ecs_response or {}),
                started,
                completed,
                run_id,
            ),
        )


def _load_metric_rows(connection, run_id: str) -> list[EvaluationRunMetric]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              metric_id,
              evaluation_run_id,
              metric_group,
              metric_name,
              metric_value,
              metric_text,
              metric_metadata,
              created_at,
              updated_at
            FROM evaluation_run_metrics
            WHERE evaluation_run_id = %s
            ORDER BY created_at ASC, metric_group ASC, metric_name ASC
            """,
            (run_id,),
        )
        rows = cursor.fetchall()

    metrics: list[EvaluationRunMetric] = []
    for row in rows:
        (
            metric_id,
            evaluation_run_id,
            metric_group,
            metric_name,
            metric_value,
            metric_text,
            metric_metadata,
            created_at,
            updated_at,
        ) = row
        metrics.append(
            EvaluationRunMetric(
                metric_id=str(metric_id),
                evaluation_run_id=str(evaluation_run_id),
                metric_group=_clean_text(metric_group),
                metric_name=_clean_text(metric_name),
                metric_value=float(metric_value) if metric_value is not None else None,
                metric_text=_clean_text(metric_text),
                metric_metadata=dict(metric_metadata or {}),
                created_at=_format_timestamp(created_at),
                updated_at=_format_timestamp(updated_at),
            )
        )
    return metrics


def _load_artifact_rows(connection, run_id: str) -> list[EvaluationRunArtifact]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              artifact_id,
              evaluation_run_id,
              artifact_type,
              label,
              s3_uri,
              content_type,
              artifact_metadata,
              created_at,
              updated_at
            FROM evaluation_run_artifacts
            WHERE evaluation_run_id = %s
            ORDER BY created_at ASC, artifact_type ASC, label ASC
            """,
            (run_id,),
        )
        rows = cursor.fetchall()

    artifacts: list[EvaluationRunArtifact] = []
    for row in rows:
        (
            artifact_id,
            evaluation_run_id,
            artifact_type,
            label,
            s3_uri,
            content_type,
            artifact_metadata,
            created_at,
            updated_at,
        ) = row
        artifacts.append(
            EvaluationRunArtifact(
                artifact_id=str(artifact_id),
                evaluation_run_id=str(evaluation_run_id),
                artifact_type=_clean_text(artifact_type),
                label=_clean_text(label),
                s3_uri=_clean_text(s3_uri),
                content_type=_clean_text(content_type),
                artifact_metadata=dict(artifact_metadata or {}),
                created_at=_format_timestamp(created_at),
                updated_at=_format_timestamp(updated_at),
            )
        )
    return artifacts


def _row_to_summary(
    row: tuple[Any, ...],
    *,
    metrics: list[EvaluationRunMetric],
    artifacts: list[EvaluationRunArtifact],
) -> EvaluationRunSummary:
    (
        evaluation_run_id,
        run_label,
        notes,
        requested_by_user_id,
        requested_by_cognito_sub,
        requested_by_email,
        judge_provider,
        judge_model,
        input_dataset_s3_uri,
        results_s3_prefix,
        course_id,
        section_id,
        scope_start_date,
        scope_end_date,
        scope_metadata,
        status,
        message,
        total_rows,
        usable_rows,
        skipped_rows,
        macro_pass_rate,
        micro_pass_rate,
        drift_rate,
        quality_decline_rate,
        code_leak_rate,
        summary,
        ecs_cluster,
        ecs_task_definition,
        ecs_container_name,
        ecs_task_arn,
        created_at,
        updated_at,
        started_at,
        completed_at,
    ) = row

    return EvaluationRunSummary(
        evaluation_run_id=_clean_text(evaluation_run_id),
        run_label=_clean_text(run_label),
        notes=_clean_text(notes),
        requested_by_user_id=(
            _clean_text(requested_by_user_id) if requested_by_user_id is not None else None
        ),
        requested_by_cognito_sub=_clean_text(requested_by_cognito_sub),
        requested_by_email=_clean_text(requested_by_email),
        judge_provider=_clean_text(judge_provider),  # type: ignore[arg-type]
        judge_model=_clean_text(judge_model),
        input_dataset_s3_uri=_clean_text(input_dataset_s3_uri),
        results_s3_prefix=_clean_text(results_s3_prefix),
        course_id=_clean_text(course_id) or None,
        section_id=_clean_text(section_id) or None,
        scope_start_date=_format_timestamp(scope_start_date) or None,
        scope_end_date=_format_timestamp(scope_end_date) or None,
        scope_metadata=dict(scope_metadata or {}),
        status=_clean_text(status),  # type: ignore[arg-type]
        message=_clean_text(message),
        total_rows=int(total_rows or 0),
        usable_rows=int(usable_rows or 0),
        skipped_rows=int(skipped_rows or 0),
        macro_pass_rate=float(macro_pass_rate) if macro_pass_rate is not None else None,
        micro_pass_rate=float(micro_pass_rate) if micro_pass_rate is not None else None,
        drift_rate=float(drift_rate) if drift_rate is not None else None,
        quality_decline_rate=(
            float(quality_decline_rate) if quality_decline_rate is not None else None
        ),
        code_leak_rate=float(code_leak_rate) if code_leak_rate is not None else None,
        summary=dict(summary or {}),
        artifacts=artifacts,
        metrics=metrics,
        ecs_cluster=_clean_text(ecs_cluster),
        ecs_task_definition=_clean_text(ecs_task_definition),
        ecs_container_name=_clean_text(ecs_container_name),
        ecs_task_arn=_clean_text(ecs_task_arn) or None,
        created_at=_format_timestamp(created_at),
        updated_at=_format_timestamp(updated_at),
        started_at=_format_timestamp(started_at) or None,
        completed_at=_format_timestamp(completed_at) or None,
    )


def _fetch_run_row(connection, run_id: str) -> tuple[Any, ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              evaluation_run_id,
              run_label,
              notes,
              requested_by_user_id,
              requested_by_cognito_sub,
              requested_by_email,
              judge_provider,
              judge_model,
              input_dataset_s3_uri,
              results_s3_prefix,
              course_id,
              section_id,
              scope_start_date,
              scope_end_date,
              scope_metadata,
              status,
              message,
              total_rows,
              usable_rows,
              skipped_rows,
              macro_pass_rate,
              micro_pass_rate,
              drift_rate,
              quality_decline_rate,
              code_leak_rate,
              summary,
              ecs_cluster,
              ecs_task_definition,
              ecs_container_name,
              ecs_task_arn,
              created_at,
              updated_at,
              started_at,
              completed_at
            FROM evaluation_runs
            WHERE evaluation_run_id = %s
            """,
            (run_id,),
        )
        row = cursor.fetchone()
    if row is None:
        raise LookupError(f"Evaluation run not found: {run_id}")
    return row


def get_evaluation_run(
    run_id: str,
    *,
    runtime: EvaluationLaunchRuntimeConfig | None = None,
) -> EvaluationRunSummary:
    """Fetch a single evaluation run and its related rows."""

    runtime = runtime or load_evaluation_launch_runtime_config()
    if not runtime.database_url:
        raise RuntimeError("Evaluation run database URL is not configured.")

    with connect_postgres_with_retry(
        runtime.database_url,
        profile="reliable",
        connect_timeout_seconds=runtime.connect_timeout_seconds,
    ) as connection:
        row = _fetch_run_row(connection, run_id)
        metrics = _load_metric_rows(connection, run_id)
        artifacts = _load_artifact_rows(connection, run_id)
    return _row_to_summary(row, metrics=metrics, artifacts=artifacts)


def list_evaluation_runs(
    *,
    limit: int = 25,
    status: str | None = None,
    runtime: EvaluationLaunchRuntimeConfig | None = None,
) -> list[EvaluationRunSummary]:
    """List recent evaluation runs."""

    runtime = runtime or load_evaluation_launch_runtime_config()
    if not runtime.database_url:
        raise RuntimeError("Evaluation run database URL is not configured.")

    where_sql = ""
    params: list[Any] = []
    if status:
        where_sql = "WHERE status = %s"
        params.append(status)
    params.append(limit)

    with connect_postgres_with_retry(
        runtime.database_url,
        profile="reliable",
        connect_timeout_seconds=runtime.connect_timeout_seconds,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                  evaluation_run_id,
                  run_label,
                  notes,
                  requested_by_user_id,
                  requested_by_cognito_sub,
                  requested_by_email,
                  judge_provider,
                  judge_model,
                  input_dataset_s3_uri,
                  results_s3_prefix,
                  course_id,
                  section_id,
                  scope_start_date,
                  scope_end_date,
                  scope_metadata,
                  status,
                  message,
                  total_rows,
                  usable_rows,
                  skipped_rows,
                  macro_pass_rate,
                  micro_pass_rate,
                  drift_rate,
                  quality_decline_rate,
                  code_leak_rate,
                  summary,
                  ecs_cluster,
                  ecs_task_definition,
                  ecs_container_name,
                  ecs_task_arn,
                  created_at,
                  updated_at,
                  started_at,
                  completed_at
                FROM evaluation_runs
                {where_sql}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                tuple(params),
            )
            rows = cursor.fetchall()

        summaries: list[EvaluationRunSummary] = []
        for row in rows:
            run_id = str(row[0])
            metrics = _load_metric_rows(connection, run_id)
            artifacts = _load_artifact_rows(connection, run_id)
            summaries.append(
                _row_to_summary(row, metrics=metrics, artifacts=artifacts)
            )
        return summaries


def get_evaluation_overview(
    *,
    runtime: EvaluationLaunchRuntimeConfig | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Return compact aggregates for the admin dashboard."""

    runtime = runtime or load_evaluation_launch_runtime_config()
    if not runtime.database_url:
        raise RuntimeError("Evaluation run database URL is not configured.")

    with connect_postgres_with_retry(
        runtime.database_url,
        profile="reliable",
        connect_timeout_seconds=runtime.connect_timeout_seconds,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, COUNT(*)
                FROM evaluation_runs
                GROUP BY status
                """
            )
            status_counts = {str(status): int(count) for status, count in cursor.fetchall()}

            cursor.execute("SELECT COUNT(*) FROM evaluation_runs")
            total_runs_row = cursor.fetchone()
            total_runs = int(total_runs_row[0]) if total_runs_row else 0

    recent_runs = list_evaluation_runs(limit=limit, runtime=runtime)
    active_runs = status_counts.get("queued", 0) + status_counts.get("running", 0)
    return {
        "total_runs": total_runs,
        "active_runs": active_runs,
        "status_counts": status_counts,
        "recent_runs": [run.model_dump(mode="json") for run in recent_runs],
    }


def launch_evaluation_run(
    request: EvaluationRunCreate,
    *,
    current_user: CurrentUser | None = None,
    runtime: EvaluationLaunchRuntimeConfig | None = None,
    ecs_client=None,
) -> EvaluationRunSummary:
    """Register an evaluation run and launch the ECS worker."""

    runtime = runtime or load_evaluation_launch_runtime_config()
    if not runtime.database_url:
        raise RuntimeError("Evaluation run database URL is not configured.")
    if not runtime.ecs_cluster or not runtime.ecs_task_definition:
        raise RuntimeError("Evaluation ECS runtime is not configured.")
    if not runtime.ecs_log_group:
        raise RuntimeError("Evaluation ECS log group is not configured.")
    if not runtime.ecs_subnet_ids or not runtime.ecs_security_group_ids:
        raise RuntimeError("Evaluation ECS runtime requires subnets and security groups.")

    requestor = _resolve_requestor(current_user)
    run_id = uuid.uuid4().hex
    run_object_prefix = _resolve_results_object_prefix(runtime, run_id)
    run_root_prefix = _resolve_results_root_prefix(runtime, run_id)
    results_s3_prefix = f"{run_root_prefix}/results"
    dataset_s3_uri = request.dataset_s3_uri
    scope_metadata: dict[str, Any] = {}
    if request.export_scope is not None:
        scope_metadata["export_scope"] = request.export_scope.model_dump(mode="json")

    if not dataset_s3_uri:
        export_scope = request.export_scope or EvaluationRunScope()
        export_result = export_turn_snapshots_to_s3(
            database_url=runtime.database_url,
            bucket=runtime.results_bucket,
            prefix=f"{run_object_prefix}/input",
            start_date=(
                date.fromisoformat(export_scope.start_date)
                if export_scope.start_date
                else None
            ),
            end_date=(
                date.fromisoformat(export_scope.end_date)
                if export_scope.end_date
                else None
            ),
            course_id=export_scope.course_id,
            section_id=export_scope.section_id,
            profile=runtime.aws_profile,
            region=runtime.aws_region,
            connect_timeout_seconds=runtime.connect_timeout_seconds,
            tz=runtime.export_timezone,
        )
        dataset_s3_uri = export_result["dataset_s3_uri"]
        scope_metadata["export_manifest"] = export_result["manifest"]

    assert dataset_s3_uri is not None

    with connect_postgres_with_retry(
        runtime.database_url,
        profile="reliable",
        connect_timeout_seconds=runtime.connect_timeout_seconds,
    ) as connection:
        _insert_run_row(
            connection=connection,
            request=request,
            requestor=requestor,
            run_id=run_id,
            dataset_s3_uri=dataset_s3_uri,
            results_s3_prefix=results_s3_prefix,
            ecs_cluster=runtime.ecs_cluster,
            ecs_task_definition=runtime.ecs_task_definition,
            ecs_container_name=runtime.ecs_container_name,
            scope_metadata=scope_metadata,
            course_id=request.export_scope.course_id if request.export_scope else None,
            section_id=request.export_scope.section_id if request.export_scope else None,
        )

    task_overrides = _build_worker_overrides(
        runtime=runtime,
        request=request,
        run_id=run_id,
        dataset_s3_uri=dataset_s3_uri,
        results_s3_prefix=results_s3_prefix,
        requestor=requestor,
    )
    client = ecs_client or _build_ecs_client(
        region=runtime.aws_region,
        profile_name=runtime.aws_profile,
    )
    logs_client = _build_logs_client(
        region=runtime.aws_region,
        profile_name=runtime.aws_profile,
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
        _ensure_log_group(logs_client, log_group_name=runtime.ecs_log_group)
        ecs_response = client.run_task(**run_task_kwargs)
        ecs_summary = _run_task_response_to_dict(ecs_response)
        tasks = ecs_summary["tasks"]
        task_arn = None
        if tasks and isinstance(tasks[0], dict):
            task_arn = tasks[0].get("taskArn")
            if task_arn is not None:
                task_arn = str(task_arn)
        failures = ecs_summary["failures"]
        launch_failed = bool(failures) or not task_arn

        with connect_postgres_with_retry(
            runtime.database_url,
            profile="reliable",
            connect_timeout_seconds=runtime.connect_timeout_seconds,
        ) as connection:
            if launch_failed:
                message = "ECS evaluation task launch failed."
                if failures:
                    message = f"ECS evaluation task launch failed: {failures}"
                _update_run_status(
                    connection=connection,
                    run_id=run_id,
                    status="launch_failed",
                    message=message,
                    ecs_response=ecs_summary,
                    completed=True,
                )
            else:
                _update_run_status(
                    connection=connection,
                    run_id=run_id,
                    status="running",
                    message="ECS evaluation task launched.",
                    ecs_task_arn=task_arn,
                    ecs_response=ecs_summary,
                    started=True,
                )
    except Exception as exc:
        with connect_postgres_with_retry(
            runtime.database_url,
            profile="reliable",
            connect_timeout_seconds=runtime.connect_timeout_seconds,
        ) as connection:
            message = f"ECS evaluation task launch failed: {exc}"
            _update_run_status(
                connection=connection,
                run_id=run_id,
                status="launch_failed",
                message=message,
                completed=True,
            )

    return get_evaluation_run(run_id, runtime=runtime)
