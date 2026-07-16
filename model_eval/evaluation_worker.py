"""ECS/Fargate worker for offline model evaluation runs."""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
from dotenv import load_dotenv

from rag_eng.aurora_retry import connect_postgres_with_retry
from rag_eng.config import normalize_bedrock_model_id
from rag_eng.llm_clients import (
    BedrockChatConfig,
    OpenAIChatConfig,
    invoke_bedrock_chat_completion,
    invoke_openai_chat_completion,
)
from rag_eng.schemas import EvaluationRunArtifact, EvaluationRunMetric, EvaluationRunSummary
from rag_eng.ta_effectiveness_ingest import ingest_ta_effectiveness_scores

try:
    from . import eval_functions as ef
    from .prompts import macro_judge_prompt, micro_judge_prompt
except ImportError:  # pragma: no cover - direct script execution fallback
    import eval_functions as ef
    from prompts import macro_judge_prompt, micro_judge_prompt


load_dotenv()

logger = logging.getLogger(__name__)


def _env_value(source: dict[str, str], name: str, default: str = "") -> str:
    value = source.get(name)
    if value is None or value == "":
        return default
    return value


def _env_int(source: dict[str, str], name: str, default: int) -> int:
    raw = _env_value(source, name, "")
    if not raw:
        return default
    return int(raw)


def _env_float(source: dict[str, str], name: str, default: float) -> float:
    raw = _env_value(source, name, "")
    if not raw:
        return default
    return float(raw)


def _env_bool(source: dict[str, str], name: str, default: bool) -> bool:
    raw = _env_value(source, name, "")
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv_values(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _json_mapping(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object.")
    return value


def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _json_safe_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, dict):
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
    except ImportError:  # pragma: no cover - only if dependency missing
        return data
    return Jsonb(_json_safe_value(data))


def _load_json_text(text: str) -> tuple[list[dict[str, Any]], int, int]:
    stripped = text.strip()
    if not stripped:
        return [], 0, 0

    if stripped.startswith("["):
        parsed = json.loads(stripped)
        if isinstance(parsed, list):
            usable = [item for item in parsed if isinstance(item, dict)]
            skipped = len(parsed) - len(usable)
            return usable, len(parsed), skipped
        if isinstance(parsed, dict):
            return [parsed], 1, 0

    records: list[dict[str, Any]] = []
    total_rows = 0
    skipped_rows = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        total_rows += 1
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            skipped_rows += 1
            continue
        if isinstance(item, dict):
            records.append(item)
        else:
            skipped_rows += 1
    return records, total_rows, skipped_rows


def _read_local_dataset(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if path.is_dir():
        records: list[dict[str, Any]] = []
        source_files = sorted(
            [
                candidate
                for candidate in path.rglob("*")
                if candidate.is_file()
                and candidate.suffix.lower() in {".jsonl", ".json"}
            ]
        )
        total_rows = 0
        skipped_rows = 0
        for file_path in source_files:
            file_records, file_rows, file_skipped = _load_json_text(
                file_path.read_text(encoding="utf-8")
            )
            records.extend(file_records)
            total_rows += file_rows
            skipped_rows += file_skipped
        manifest = {
            "source_kind": "local-directory",
            "source_uri": str(path),
            "source_items": [str(item) for item in source_files],
            "total_rows": total_rows,
            "usable_rows": len(records),
            "skipped_rows": skipped_rows,
        }
        return records, manifest

    if not path.is_file():
        raise FileNotFoundError(f"Dataset not found: {path}")

    records, total_rows, skipped_rows = _load_json_text(
        path.read_text(encoding="utf-8")
    )
    manifest = {
        "source_kind": "local-file",
        "source_uri": str(path),
        "source_items": [str(path)],
        "total_rows": total_rows,
        "usable_rows": len(records),
        "skipped_rows": skipped_rows,
    }
    return records, manifest


def _build_s3_client(*, region: str, profile_name: str | None):
    import boto3

    session = boto3.Session(profile_name=profile_name, region_name=region)
    return session.client("s3")


def _read_s3_dataset(
    s3_uri: str,
    *,
    region: str,
    profile_name: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bucket, key = _parse_s3_uri(s3_uri)
    client = _build_s3_client(region=region, profile_name=profile_name)
    source_items: list[str] = []

    def _load_object(object_key: str) -> tuple[list[dict[str, Any]], int, int]:
        response = client.get_object(Bucket=bucket, Key=object_key)
        body = response["Body"].read().decode("utf-8")
        return _load_json_text(body)

    try:
        client.head_object(Bucket=bucket, Key=key)
    except Exception:
        paginator = client.get_paginator("list_objects_v2")
        prefixes = key.rstrip("/")
        records: list[dict[str, Any]] = []
        total_rows = 0
        skipped_rows = 0
        for page in paginator.paginate(Bucket=bucket, Prefix=prefixes):
            for item in page.get("Contents", []):
                object_key = item.get("Key", "")
                if not object_key or not object_key.lower().endswith((".jsonl", ".json")):
                    continue
                source_items.append(f"s3://{bucket}/{object_key}")
                file_records, file_rows, file_skipped = _load_object(object_key)
                records.extend(file_records)
                total_rows += file_rows
                skipped_rows += file_skipped
        manifest = {
            "source_kind": "s3-prefix",
            "source_uri": s3_uri,
            "source_items": source_items,
            "total_rows": total_rows,
            "usable_rows": len(records),
            "skipped_rows": skipped_rows,
        }
        return records, manifest

    records, total_rows, skipped_rows = _load_object(key)
    manifest = {
        "source_kind": "s3-object",
        "source_uri": s3_uri,
        "source_items": [s3_uri],
        "total_rows": total_rows,
        "usable_rows": len(records),
        "skipped_rows": skipped_rows,
    }
    return records, manifest


def load_dataset_records(
    source_uri: str,
    *,
    region: str,
    profile_name: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load canonical turn snapshots or legacy eval rows."""
    if source_uri.startswith("s3://"):
        return _read_s3_dataset(
            source_uri,
            region=region,
            profile_name=profile_name,
        )
    return _read_local_dataset(Path(source_uri).expanduser().resolve())


@dataclass(frozen=True)
class EvaluationWorkerSettings:
    """Resolved runtime settings for an evaluation run."""

    evaluation_run_id: str
    judge_provider: str
    judge_model: str
    dataset_s3_uri: str
    results_s3_prefix: str
    output_dir: Path
    aws_region: str
    aws_profile: str | None
    s3_data_bucket: str
    openai_base_url: str
    openai_api_key: str | None
    database_url: str | None
    write_aurora: bool
    requested_by_user_id: str | None
    requested_by_cognito_sub: str
    requested_by_email: str
    run_label: str
    notes: str
    course_id: str | None
    section_id: str | None
    scope_start_date: str | None
    scope_end_date: str | None
    scope_metadata: dict[str, Any] = field(default_factory=dict)
    ecs_cluster: str = ""
    ecs_task_definition: str = ""
    ecs_container_name: str = ""
    ecs_task_arn: str | None = None
    homework_n: int = 100000
    study_n: int = 100000
    judge_temperature: float = 0.0
    judge_top_p: float = 0.9
    judge_timeout_seconds: float = 120.0
    judge_max_concurrency: int = 8
    judge_max_tokens: int = 2048
    export_timezone: str = "America/Los_Angeles"

    def request_payload(self) -> dict[str, Any]:
        return {
            "evaluation_run_id": self.evaluation_run_id,
            "judge_provider": self.judge_provider,
            "judge_model": self.judge_model,
            "dataset_s3_uri": self.dataset_s3_uri,
            "results_s3_prefix": self.results_s3_prefix,
            "run_label": self.run_label,
            "notes": self.notes,
            "course_id": self.course_id,
            "section_id": self.section_id,
            "scope_start_date": self.scope_start_date,
            "scope_end_date": self.scope_end_date,
            "scope_metadata": self.scope_metadata,
            "requested_by_user_id": self.requested_by_user_id,
            "requested_by_cognito_sub": self.requested_by_cognito_sub,
            "requested_by_email": self.requested_by_email,
            "ecs_cluster": self.ecs_cluster,
            "ecs_task_definition": self.ecs_task_definition,
            "ecs_container_name": self.ecs_container_name,
            "ecs_task_arn": self.ecs_task_arn,
            "homework_n": self.homework_n,
            "study_n": self.study_n,
            "judge_temperature": self.judge_temperature,
            "judge_top_p": self.judge_top_p,
            "judge_timeout_seconds": self.judge_timeout_seconds,
            "judge_max_concurrency": self.judge_max_concurrency,
            "judge_max_tokens": self.judge_max_tokens,
            "export_timezone": self.export_timezone,
        }


def load_worker_settings(argv: list[str] | None = None) -> EvaluationWorkerSettings:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    env = dict(os.environ)

    evaluation_run_id = args.evaluation_run_id or env.get("EVALUATION_RUN_ID") or uuid.uuid4().hex
    output_dir = Path(
        args.output_dir
        or env.get("EVALUATION_OUTPUT_DIR")
        or f"/tmp/evaluation_runs/{evaluation_run_id}"
    ).expanduser().resolve()
    results_prefix = args.results_s3_prefix or env.get("EVALUATION_RESULTS_PREFIX") or ""
    if results_prefix.startswith("s3://"):
        resolved_results_prefix = results_prefix.rstrip("/")
    else:
        bucket = _env_value(env, "S3_DATA_BUCKET", "codingrabbit-data-dev")
        normalized_prefix = results_prefix.strip("/") or "evaluation/offline"
        resolved_results_prefix = f"s3://{bucket}/{normalized_prefix}/{evaluation_run_id}"

    scope_metadata_raw = args.scope_metadata_json or env.get("EVALUATION_SCOPE_METADATA_JSON") or "{}"
    scope_metadata = _json_mapping(scope_metadata_raw)

    return EvaluationWorkerSettings(
        evaluation_run_id=evaluation_run_id,
        judge_provider=(args.judge_provider or env.get("EVALUATION_DEFAULT_JUDGE_PROVIDER") or "bedrock").strip().lower(),
        judge_model=(args.judge_model or env.get("EVALUATION_DEFAULT_JUDGE_MODEL") or "us.anthropic.claude-sonnet-4-6").strip(),
        dataset_s3_uri=(args.dataset_s3_uri or env.get("EVALUATION_DATASET_S3_URI") or "").strip(),
        results_s3_prefix=resolved_results_prefix,
        output_dir=output_dir,
        aws_region=(args.aws_region or env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or "us-east-1").strip(),
        aws_profile=args.aws_profile or env.get("AWS_PROFILE") or None,
        s3_data_bucket=_env_value(env, "S3_DATA_BUCKET", "codingrabbit-data-dev"),
        openai_base_url=_env_value(env, "OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_api_key=env.get("OPENAI_API_KEY"),
        database_url=args.database_url or env.get("EVALUATION_DATABASE_URL") or env.get("COURSE_REGISTRY_DATABASE_URL") or env.get("DATABASE_URL"),
        write_aurora=args.write_aurora if args.write_aurora is not None else _env_bool(env, "EVALUATION_WRITE_AURORA", True),
        requested_by_user_id=args.requested_by_user_id or env.get("EVALUATION_REQUESTED_BY_USER_ID") or None,
        requested_by_cognito_sub=args.requested_by_cognito_sub or env.get("EVALUATION_REQUESTED_BY_COGNITO_SUB") or "",
        requested_by_email=args.requested_by_email or env.get("EVALUATION_REQUESTED_BY_EMAIL") or "",
        run_label=args.run_label or env.get("EVALUATION_RUN_LABEL") or "",
        notes=args.notes or env.get("EVALUATION_RUN_NOTES") or "",
        course_id=args.course_id or env.get("EVALUATION_COURSE_ID") or None,
        section_id=args.section_id or env.get("EVALUATION_SECTION_ID") or None,
        scope_start_date=args.scope_start_date or env.get("EVALUATION_SCOPE_START_DATE") or None,
        scope_end_date=args.scope_end_date or env.get("EVALUATION_SCOPE_END_DATE") or None,
        scope_metadata=scope_metadata,
        ecs_cluster=_env_value(env, "EVALUATION_WORKER_ECS_CLUSTER", ""),
        ecs_task_definition=_env_value(env, "EVALUATION_WORKER_ECS_TASK_DEFINITION", ""),
        ecs_container_name=_env_value(env, "EVALUATION_WORKER_ECS_CONTAINER_NAME", ""),
        ecs_task_arn=env.get("ECS_TASK_ARN") or None,
        homework_n=_env_int(env, "EVALUATION_HOMEWORK_N", 100000),
        study_n=_env_int(env, "EVALUATION_STUDY_N", 100000),
        judge_temperature=_env_float(env, "EVALUATION_JUDGE_TEMPERATURE", 0.0),
        judge_top_p=_env_float(env, "EVALUATION_JUDGE_TOP_P", 0.9),
        judge_timeout_seconds=_env_float(env, "EVALUATION_JUDGE_TIMEOUT_SECONDS", 120.0),
        judge_max_concurrency=_env_int(env, "EVALUATION_JUDGE_MAX_CONCURRENCY", 8),
        judge_max_tokens=_env_int(env, "EVALUATION_JUDGE_MAX_TOKENS", 2048),
        export_timezone=_env_value(env, "EVALUATION_EXPORT_TZ", "America/Los_Angeles"),
    )


class _BatchResult:
    """Mimic the LangChain result object expected by the eval helpers."""

    __slots__ = ("content",)

    def __init__(self, content: str):
        self.content = content


def _run_batch(
    prompts: list[str],
    invoke,
    *,
    max_concurrency: int,
    return_exceptions: bool,
) -> list[object]:
    results: list[object] = [None] * len(prompts)
    workers = max(1, min(max_concurrency, len(prompts) or 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(invoke, prompt): index for index, prompt in enumerate(prompts)}
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:  # pragma: no cover - exercised via return_exceptions
                if not return_exceptions:
                    raise
                results[index] = exc
    return results


class OpenAIJudgeProvider:
    """Batch adapter for OpenAI-based judge runs."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        temperature: float,
        top_p: float,
        max_concurrency: int,
    ) -> None:
        self._config = OpenAIChatConfig(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            top_p=top_p,
        )
        self._max_concurrency = max_concurrency

    def batch(
        self,
        prompts: list[str],
        config: dict[str, Any] | None = None,
        return_exceptions: bool = False,
    ) -> list[object]:
        limit = (config or {}).get("max_concurrency", self._max_concurrency)
        return _run_batch(
            prompts,
            lambda prompt: _BatchResult(
                invoke_openai_chat_completion(prompt, self._config)
            ),
            max_concurrency=int(limit),
            return_exceptions=return_exceptions,
        )


class BedrockJudgeProvider:
    """Batch adapter for Bedrock-based judge runs."""

    def __init__(
        self,
        *,
        region: str,
        model_id: str,
        timeout_seconds: float,
        temperature: float,
        top_p: float,
        max_tokens: int,
        max_concurrency: int,
        profile_name: str | None = None,
    ) -> None:
        self._config = BedrockChatConfig(
            region=region,
            model_id=normalize_bedrock_model_id(model_id),
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            profile_name=profile_name,
        )
        self._max_concurrency = max_concurrency

    def batch(
        self,
        prompts: list[str],
        config: dict[str, Any] | None = None,
        return_exceptions: bool = False,
    ) -> list[object]:
        limit = (config or {}).get("max_concurrency", self._max_concurrency)
        return _run_batch(
            prompts,
            lambda prompt: _BatchResult(
                invoke_bedrock_chat_completion(
                    [{"role": "user", "content": prompt}],
                    self._config,
                )
            ),
            max_concurrency=int(limit),
            return_exceptions=return_exceptions,
        )


def _build_judge_provider(settings: EvaluationWorkerSettings):
    if settings.judge_provider == "openai":
        api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI judge runs.")
        return OpenAIJudgeProvider(
            api_key=api_key,
            base_url=settings.openai_base_url,
            model=settings.judge_model,
            timeout_seconds=settings.judge_timeout_seconds,
            temperature=settings.judge_temperature,
            top_p=settings.judge_top_p,
            max_concurrency=settings.judge_max_concurrency,
        )
    if settings.judge_provider == "bedrock":
        return BedrockJudgeProvider(
            region=settings.aws_region,
            model_id=settings.judge_model,
            timeout_seconds=settings.judge_timeout_seconds,
            temperature=settings.judge_temperature,
            top_p=settings.judge_top_p,
            max_tokens=settings.judge_max_tokens,
            max_concurrency=settings.judge_max_concurrency,
            profile_name=settings.aws_profile,
        )
    raise ValueError(f"Unsupported judge provider: {settings.judge_provider}")


def _artifact_content_type(path: Path) -> str:
    content_type, _ = mimetypes.guess_type(str(path))
    if content_type:
        return content_type
    if path.suffix.lower() in {".json", ".jsonl"}:
        return "application/json"
    if path.suffix.lower() == ".csv":
        return "text/csv"
    if path.suffix.lower() == ".png":
        return "image/png"
    return "application/octet-stream"


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _save_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _summary_metric_rows(
    *,
    run_id: str,
    prefix: str,
    summary: dict[str, Any],
    macro_pass_rate: float | None,
    micro_pass_rate: float | None,
    drift_rate: float | None,
    quality_decline_rate: float | None,
    code_leak_rate: float | None,
) -> list[EvaluationRunMetric]:
    now = datetime.now(timezone.utc).isoformat()
    rows: list[EvaluationRunMetric] = []
    entries = [
        ("summary", "macro_pass_rate", macro_pass_rate),
        ("summary", "micro_pass_rate", micro_pass_rate),
        ("summary", "drift_rate", drift_rate),
        ("summary", "quality_decline_rate", quality_decline_rate),
        ("summary", "code_leak_rate", code_leak_rate),
        ("summary", "total_rows", summary.get("total_rows")),
        ("summary", "usable_rows", summary.get("usable_rows")),
        ("summary", "skipped_rows", summary.get("skipped_rows")),
    ]
    for metric_group, metric_name, metric_value in entries:
        rows.append(
            EvaluationRunMetric(
                metric_id=str(uuid.uuid4()),
                evaluation_run_id=run_id,
                metric_group=f"{prefix}.{metric_group}",
                metric_name=metric_name,
                metric_value=metric_value if metric_value is None else float(metric_value),
                metric_text="" if metric_value is None else str(metric_value),
                metric_metadata={"source": prefix},
                created_at=now,
                updated_at=now,
            )
        )
    return rows


def _per_metric_rows(
    *,
    run_id: str,
    prefix: str,
    per_metric: dict[str, dict[str, Any]],
) -> list[EvaluationRunMetric]:
    now = datetime.now(timezone.utc).isoformat()
    rows: list[EvaluationRunMetric] = []
    for metric_name, payload in per_metric.items():
        rows.append(
            EvaluationRunMetric(
                metric_id=str(uuid.uuid4()),
                evaluation_run_id=run_id,
                metric_group=prefix,
                metric_name=metric_name,
                metric_value=payload.get("pass_rate"),
                metric_text=f'{payload.get("Number of ones", 0)}/{payload.get("Number of samples", 0)}',
                metric_metadata=payload,
                created_at=now,
                updated_at=now,
            )
        )
    return rows


def _artifact_rows(
    *,
    run_id: str,
    output_dir: Path,
    results_prefix: str,
    relative_paths: list[Path],
) -> list[EvaluationRunArtifact]:
    now = datetime.now(timezone.utc).isoformat()
    artifacts: list[EvaluationRunArtifact] = []
    for rel_path in relative_paths:
        artifact_type = rel_path.suffix.lstrip(".") or rel_path.name
        if rel_path.name == "summary.json":
            artifact_type = "summary"
        elif rel_path.name == "manifest.json":
            artifact_type = "manifest"
        elif rel_path.name.endswith("_results.json"):
            artifact_type = rel_path.name.replace("_results.json", "")
        elif rel_path.name.endswith("_spot_check.csv"):
            artifact_type = rel_path.name.replace(".csv", "")
        elif rel_path.name == "disagreements.csv":
            artifact_type = "disagreements"
        elif rel_path.parts[0] == "charts":
            artifact_type = "chart"
        artifacts.append(
            EvaluationRunArtifact(
                artifact_id=str(uuid.uuid4()),
                evaluation_run_id=run_id,
                artifact_type=artifact_type,
                label=rel_path.as_posix(),
                s3_uri=f"{results_prefix.rstrip('/')}/{rel_path.as_posix()}",
                content_type=_artifact_content_type(output_dir / rel_path),
                artifact_metadata={
                    "relative_path": rel_path.as_posix(),
                    "results_prefix": results_prefix,
                },
                created_at=now,
                updated_at=now,
            )
        )
    return artifacts


def _upload_directory_to_s3(
    *,
    output_dir: Path,
    results_prefix: str,
    region: str,
    profile_name: str | None,
) -> list[Path]:
    bucket, key_prefix = _parse_s3_uri(results_prefix)
    client = _build_s3_client(region=region, profile_name=profile_name)
    uploaded: list[Path] = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(output_dir)
        key = "/".join(
            part.strip("/")
            for part in [key_prefix.rstrip("/"), rel_path.as_posix()]
            if part.strip("/")
        )
        client.upload_file(
            str(path),
            bucket,
            key,
            ExtraArgs={"ContentType": _artifact_content_type(path)},
        )
        uploaded.append(rel_path)
    return uploaded


def _aurora_connection(settings: EvaluationWorkerSettings):
    if not settings.database_url:
        raise RuntimeError("No Aurora database URL configured for evaluation runs.")
    return connect_postgres_with_retry(
        settings.database_url,
        profile="reliable",
    )


def _persist_run_state(
    *,
    settings: EvaluationWorkerSettings,
    summary_payload: dict[str, Any],
    status: str,
    message: str,
    total_rows: int = 0,
    usable_rows: int = 0,
    skipped_rows: int = 0,
    macro_pass_rate: float | None = None,
    micro_pass_rate: float | None = None,
    drift_rate: float | None = None,
    quality_decline_rate: float | None = None,
    code_leak_rate: float | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    metrics: list[EvaluationRunMetric] | None = None,
    artifacts: list[EvaluationRunArtifact] | None = None,
) -> None:
    if not settings.write_aurora or not settings.database_url:
        return

    run_id = settings.evaluation_run_id
    request_payload = settings.request_payload()
    ecs_response = {
        "output_dir": str(settings.output_dir),
        "results_s3_prefix": settings.results_s3_prefix,
        "status": status,
    }
    with _aurora_connection(settings) as connection:
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
                  request_payload,
                  ecs_response,
                  started_at,
                  completed_at
                ) VALUES (
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
                  %(total_rows)s,
                  %(usable_rows)s,
                  %(skipped_rows)s,
                  %(macro_pass_rate)s,
                  %(micro_pass_rate)s,
                  %(drift_rate)s,
                  %(quality_decline_rate)s,
                  %(code_leak_rate)s,
                  %(summary)s,
                  %(ecs_cluster)s,
                  %(ecs_task_definition)s,
                  %(ecs_container_name)s,
                  %(ecs_task_arn)s,
                  %(request_payload)s,
                  %(ecs_response)s,
                  %(started_at)s,
                  %(completed_at)s
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
                  total_rows = EXCLUDED.total_rows,
                  usable_rows = EXCLUDED.usable_rows,
                  skipped_rows = EXCLUDED.skipped_rows,
                  macro_pass_rate = EXCLUDED.macro_pass_rate,
                  micro_pass_rate = EXCLUDED.micro_pass_rate,
                  drift_rate = EXCLUDED.drift_rate,
                  quality_decline_rate = EXCLUDED.quality_decline_rate,
                  code_leak_rate = EXCLUDED.code_leak_rate,
                  summary = EXCLUDED.summary,
                  ecs_cluster = EXCLUDED.ecs_cluster,
                  ecs_task_definition = EXCLUDED.ecs_task_definition,
                  ecs_container_name = EXCLUDED.ecs_container_name,
                  ecs_task_arn = EXCLUDED.ecs_task_arn,
                  request_payload = EXCLUDED.request_payload,
                  ecs_response = EXCLUDED.ecs_response,
                  started_at = COALESCE(evaluation_runs.started_at, EXCLUDED.started_at),
                  completed_at = COALESCE(EXCLUDED.completed_at, evaluation_runs.completed_at),
                  updated_at = now()
                """,
                {
                    "evaluation_run_id": run_id,
                    "run_label": settings.run_label,
                    "notes": settings.notes,
                    "requested_by_user_id": settings.requested_by_user_id,
                    "requested_by_cognito_sub": settings.requested_by_cognito_sub,
                    "requested_by_email": settings.requested_by_email,
                    "judge_provider": settings.judge_provider,
                    "judge_model": settings.judge_model,
                    "input_dataset_s3_uri": settings.dataset_s3_uri,
                    "results_s3_prefix": settings.results_s3_prefix,
                    "course_id": settings.course_id,
                    "section_id": settings.section_id,
                    "scope_start_date": settings.scope_start_date,
                    "scope_end_date": settings.scope_end_date,
                    "scope_metadata": _json_adapter(summary_payload.get("scope_metadata", {})),
                    "status": status,
                    "message": message,
                    "total_rows": total_rows,
                    "usable_rows": usable_rows,
                    "skipped_rows": skipped_rows,
                    "macro_pass_rate": macro_pass_rate,
                    "micro_pass_rate": micro_pass_rate,
                    "drift_rate": drift_rate,
                    "quality_decline_rate": quality_decline_rate,
                    "code_leak_rate": code_leak_rate,
                    "summary": _json_adapter(summary_payload),
                    "ecs_cluster": settings.ecs_cluster,
                    "ecs_task_definition": settings.ecs_task_definition,
                    "ecs_container_name": settings.ecs_container_name,
                    "ecs_task_arn": settings.ecs_task_arn,
                    "request_payload": _json_adapter(request_payload),
                    "ecs_response": _json_adapter(ecs_response),
                    "started_at": started_at,
                    "completed_at": completed_at,
                },
            )

            if status not in {"succeeded", "failed", "launch_failed"}:
                return

            if metrics is None:
                metrics = []
            if artifacts is None:
                artifacts = []

            cursor.execute(
                "DELETE FROM evaluation_run_metrics WHERE evaluation_run_id = %s",
                (run_id,),
            )
            cursor.execute(
                "DELETE FROM evaluation_run_artifacts WHERE evaluation_run_id = %s",
                (run_id,),
            )

            for metric in metrics:
                cursor.execute(
                    """
                    INSERT INTO evaluation_run_metrics (
                      metric_id,
                      evaluation_run_id,
                      metric_group,
                      metric_name,
                      metric_value,
                      metric_text,
                      metric_metadata
                    ) VALUES (
                      %(metric_id)s,
                      %(evaluation_run_id)s,
                      %(metric_group)s,
                      %(metric_name)s,
                      %(metric_value)s,
                      %(metric_text)s,
                      %(metric_metadata)s
                    )
                    """,
                    {
                        "metric_id": metric.metric_id,
                        "evaluation_run_id": metric.evaluation_run_id,
                        "metric_group": metric.metric_group,
                        "metric_name": metric.metric_name,
                        "metric_value": metric.metric_value,
                        "metric_text": metric.metric_text,
                        "metric_metadata": _json_adapter(metric.metric_metadata),
                    },
                )

            for artifact in artifacts:
                cursor.execute(
                    """
                    INSERT INTO evaluation_run_artifacts (
                      artifact_id,
                      evaluation_run_id,
                      artifact_type,
                      label,
                      s3_uri,
                      content_type,
                      artifact_metadata
                    ) VALUES (
                      %(artifact_id)s,
                      %(evaluation_run_id)s,
                      %(artifact_type)s,
                      %(label)s,
                      %(s3_uri)s,
                      %(content_type)s,
                      %(artifact_metadata)s
                    )
                    """,
                    {
                        "artifact_id": artifact.artifact_id,
                        "evaluation_run_id": artifact.evaluation_run_id,
                        "artifact_type": artifact.artifact_type,
                        "label": artifact.label,
                        "s3_uri": artifact.s3_uri,
                        "content_type": artifact.content_type,
                        "artifact_metadata": _json_adapter(artifact.artifact_metadata),
                    },
                )


def _render_charts(
    *,
    output_dir: Path,
    macro_results: list[dict[str, Any]],
    micro_results: list[dict[str, Any]],
    dataset_name: str,
) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    charts_dir = output_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    if getattr(ef, "plt", None) is None:
        return saved

    original_show = ef.plt.show

    def _savefig(*_args, **_kwargs):
        path = charts_dir / f"chart_{len(saved) + 1}.png"
        ef.plt.savefig(path)
        ef.plt.close()
        saved.append(path.relative_to(output_dir))

    ef.plt.show = _savefig
    try:
        ef.plot_metric_ci(micro_results, ef.micro_metrics, dataset_name + " MICRO PASS RATE")
        ef.plot_metric_ci(macro_results, ef.macro_metrics, dataset_name + " MACRO PASS RATE")
        ef.plot_cat(micro_results, ef.micro_groups, dataset_name + " MICRO BY CATEGORY")
        ef.plot_cat(macro_results, ef.macro_groups, dataset_name + " MACRO BY CATEGORY")
    finally:
        ef.plt.show = original_show

    return saved


def _build_dataset_name(settings: EvaluationWorkerSettings) -> str:
    parts = [settings.run_label.strip(), settings.course_id or "", settings.section_id or ""]
    label = " ".join(part for part in parts if part)
    return label or settings.evaluation_run_id


def run_evaluation_job(settings: EvaluationWorkerSettings) -> EvaluationRunSummary:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    dataset_name = _build_dataset_name(settings)

    records, manifest = load_dataset_records(
        settings.dataset_s3_uri,
        region=settings.aws_region,
        profile_name=settings.aws_profile,
    )
    if not records:
        raise RuntimeError("No usable evaluation rows were found.")

    ef.results_dir = str(settings.output_dir)
    ef.homework_number = settings.homework_n
    ef.study_number = settings.study_n

    _persist_run_state(
        settings=settings,
        summary_payload={"scope_metadata": manifest | settings.scope_metadata},
        status="running",
        message="Evaluation worker started.",
        total_rows=manifest["total_rows"],
        usable_rows=manifest["usable_rows"],
        skipped_rows=manifest["skipped_rows"],
        started_at=datetime.now(timezone.utc),
    )

    macro_samples = ef.stratified_sample(ef.build_Macro_samples(records))
    micro_samples = ef.build_micro_samples([sample["raw_convo"] for sample in macro_samples])
    judge_model = _build_judge_provider(settings)

    macro_results = ef.run_marco_eval(macro_samples, judge_model, macro_judge_prompt)
    micro_results = ef.run_mirco_eval(micro_samples, judge_model, micro_judge_prompt)
    drift = ef.compute_drift(micro_results)

    # Join judge output back to students/sections and persist it for the
    # professor-facing TA Effectiveness dashboard. This never reads
    # settings.section_id/course_id — each session's own tutor_sessions row
    # supplies those, so a run spanning many sections fans out correctly.
    # A bug here must not crash the run's primary bookkeeping below.
    if settings.write_aurora and settings.database_url:
        try:
            with _aurora_connection(settings) as connection:
                ingest_ta_effectiveness_scores(
                    connection,
                    evaluation_run_id=settings.evaluation_run_id,
                    macro_results=macro_results,
                    micro_results=micro_results,
                    drift_results=drift,
                    macro_metric_names=ef.macro_metrics,
                    micro_metric_names=ef.micro_metrics,
                    scored_at=datetime.now(timezone.utc),
                )
        except Exception:
            logger.exception(
                "TA effectiveness ingestion failed for run %s",
                settings.evaluation_run_id,
            )

    macro_df = pd.DataFrame(macro_results)
    micro_df = pd.DataFrame(micro_results)
    macro_pass_rate = (
        float(macro_df["passed"].dropna().mean()) if len(macro_df) else None
    )
    micro_pass_rate = (
        float(micro_df["passed"].dropna().mean()) if len(micro_df) else None
    )
    drift_rate = drift.get("total_drift_rate")
    quality_decline_rate = drift.get("qaulity_decline_rate")
    code_leak_rate = drift.get("code_leak_rate")

    macro_metric_summary = ef.per_metric_pass_rate(macro_df, ef.macro_metrics)
    micro_metric_summary = ef.per_metric_pass_rate(micro_df, ef.micro_metrics)
    disagreements = ef.compare_judge(micro_results, dataset_name)
    macro_spot_check = ef.spot_check(macro_results, ef.macro_metrics, dataset_name)
    micro_spot_check = ef.spot_check(micro_results, ef.micro_metrics, dataset_name)

    _save_json(settings.output_dir / "manifest.json", manifest | settings.scope_metadata)
    _save_json(settings.output_dir / "macro_results.json", macro_results)
    _save_json(settings.output_dir / "micro_results.json", micro_results)
    _save_json(settings.output_dir / "drift_results.json", drift)

    summary_payload = {
        "dataset_manifest": manifest,
        "scope_metadata": settings.scope_metadata,
        "dataset_name": dataset_name,
        "judge_provider": settings.judge_provider,
        "judge_model": settings.judge_model,
        "total_rows": manifest["total_rows"],
        "usable_rows": manifest["usable_rows"],
        "skipped_rows": manifest["skipped_rows"],
        "macro_pass_rate": macro_pass_rate,
        "micro_pass_rate": micro_pass_rate,
        "drift_summary": {
            "total_drift_rate": drift_rate,
            "quality_decline_rate": quality_decline_rate,
            "code_leak_rate": code_leak_rate,
            "num_convos": drift.get("Num_convos"),
        },
        "macro_metric_summary": macro_metric_summary,
        "micro_metric_summary": micro_metric_summary,
        "results_s3_prefix": settings.results_s3_prefix,
    }
    _save_json(settings.output_dir / "summary.json", summary_payload)
    _save_csv(settings.output_dir / "disagreements.csv", disagreements)
    _save_csv(settings.output_dir / "macro_spot_check.csv", macro_spot_check)
    _save_csv(settings.output_dir / "micro_spot_check.csv", micro_spot_check)

    rendered_chart_paths = _render_charts(
        output_dir=settings.output_dir,
        macro_results=macro_results,
        micro_results=micro_results,
        dataset_name=dataset_name,
    )

    uploaded_rel_paths = _upload_directory_to_s3(
        output_dir=settings.output_dir,
        results_prefix=settings.results_s3_prefix,
        region=settings.aws_region,
        profile_name=settings.aws_profile,
    )
    artifact_paths = sorted(
        {
            *(Path("manifest.json"),),
            *(Path("summary.json"),),
            *(Path("macro_results.json"),),
            *(Path("micro_results.json"),),
            *(Path("drift_results.json"),),
            *(Path("disagreements.csv"),),
            *(Path("macro_spot_check.csv"),),
            *(Path("micro_spot_check.csv"),),
            *rendered_chart_paths,
            *uploaded_rel_paths,
        },
        key=lambda item: item.as_posix(),
    )

    metric_rows = [
        *_summary_metric_rows(
            run_id=settings.evaluation_run_id,
            prefix="run",
            summary=summary_payload,
            macro_pass_rate=macro_pass_rate,
            micro_pass_rate=micro_pass_rate,
            drift_rate=drift_rate,
            quality_decline_rate=quality_decline_rate,
            code_leak_rate=code_leak_rate,
        ),
        *_per_metric_rows(
            run_id=settings.evaluation_run_id,
            prefix="macro",
            per_metric=macro_metric_summary,
        ),
        *_per_metric_rows(
            run_id=settings.evaluation_run_id,
            prefix="micro",
            per_metric=micro_metric_summary,
        ),
    ]
    artifact_rows = _artifact_rows(
        run_id=settings.evaluation_run_id,
        output_dir=settings.output_dir,
        results_prefix=settings.results_s3_prefix,
        relative_paths=artifact_paths,
    )
    summary = EvaluationRunSummary(
        evaluation_run_id=settings.evaluation_run_id,
        run_label=settings.run_label,
        notes=settings.notes,
        requested_by_user_id=settings.requested_by_user_id,
        requested_by_cognito_sub=settings.requested_by_cognito_sub,
        requested_by_email=settings.requested_by_email,
        judge_provider=settings.judge_provider,  # type: ignore[arg-type]
        judge_model=settings.judge_model,
        input_dataset_s3_uri=settings.dataset_s3_uri,
        results_s3_prefix=settings.results_s3_prefix,
        course_id=settings.course_id,
        section_id=settings.section_id,
        scope_start_date=settings.scope_start_date,
        scope_end_date=settings.scope_end_date,
        scope_metadata=settings.scope_metadata,
        status="succeeded",
        message="Evaluation completed successfully.",
        total_rows=manifest["total_rows"],
        usable_rows=manifest["usable_rows"],
        skipped_rows=manifest["skipped_rows"],
        macro_pass_rate=macro_pass_rate,
        micro_pass_rate=micro_pass_rate,
        drift_rate=drift_rate,
        quality_decline_rate=quality_decline_rate,
        code_leak_rate=code_leak_rate,
        summary=summary_payload,
        artifacts=artifact_rows,
        metrics=metric_rows,
        ecs_cluster=settings.ecs_cluster,
        ecs_task_definition=settings.ecs_task_definition,
        ecs_container_name=settings.ecs_container_name,
        ecs_task_arn=settings.ecs_task_arn,
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
    )

    _persist_run_state(
        settings=settings,
        summary_payload=summary_payload,
        status="succeeded",
        message="Evaluation completed successfully.",
        total_rows=manifest["total_rows"],
        usable_rows=manifest["usable_rows"],
        skipped_rows=manifest["skipped_rows"],
        macro_pass_rate=macro_pass_rate,
        micro_pass_rate=micro_pass_rate,
        drift_rate=drift_rate,
        quality_decline_rate=quality_decline_rate,
        code_leak_rate=code_leak_rate,
        started_at=datetime.fromisoformat(summary.started_at),
        completed_at=datetime.fromisoformat(summary.completed_at),
        metrics=metric_rows,
        artifacts=artifact_rows,
    )
    return summary


def _failure_summary(settings: EvaluationWorkerSettings, message: str) -> EvaluationRunSummary:
    return EvaluationRunSummary(
        evaluation_run_id=settings.evaluation_run_id,
        run_label=settings.run_label,
        notes=settings.notes,
        requested_by_user_id=settings.requested_by_user_id,
        requested_by_cognito_sub=settings.requested_by_cognito_sub,
        requested_by_email=settings.requested_by_email,
        judge_provider=settings.judge_provider,  # type: ignore[arg-type]
        judge_model=settings.judge_model,
        input_dataset_s3_uri=settings.dataset_s3_uri,
        results_s3_prefix=settings.results_s3_prefix,
        course_id=settings.course_id,
        section_id=settings.section_id,
        scope_start_date=settings.scope_start_date,
        scope_end_date=settings.scope_end_date,
        scope_metadata=settings.scope_metadata,
        status="failed",
        message=message,
        summary={"error": message},
        ecs_cluster=settings.ecs_cluster,
        ecs_task_definition=settings.ecs_task_definition,
        ecs_container_name=settings.ecs_container_name,
        ecs_task_arn=settings.ecs_task_arn,
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an offline evaluation job.")
    parser.add_argument("--evaluation-run-id", default=None)
    parser.add_argument("--judge-provider", default=None)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--dataset-s3-uri", default=None)
    parser.add_argument("--results-s3-prefix", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--requested-by-user-id", default=None)
    parser.add_argument("--requested-by-cognito-sub", default=None)
    parser.add_argument("--requested-by-email", default=None)
    parser.add_argument("--run-label", default=None)
    parser.add_argument("--notes", default=None)
    parser.add_argument("--course-id", default=None)
    parser.add_argument("--section-id", default=None)
    parser.add_argument("--scope-start-date", default=None)
    parser.add_argument("--scope-end-date", default=None)
    parser.add_argument("--scope-metadata-json", default=None)
    parser.add_argument("--aws-region", default=None)
    parser.add_argument("--aws-profile", default=None)
    parser.add_argument("--homework-n", type=int, default=None)
    parser.add_argument("--study-n", type=int, default=None)
    parser.add_argument("--judge-temperature", type=float, default=None)
    parser.add_argument("--judge-top-p", type=float, default=None)
    parser.add_argument("--judge-timeout-seconds", type=float, default=None)
    parser.add_argument("--judge-max-concurrency", type=int, default=None)
    parser.add_argument("--judge-max-tokens", type=int, default=None)
    parser.add_argument("--write-aurora", dest="write_aurora", action="store_true")
    parser.add_argument("--no-write-aurora", dest="write_aurora", action="store_false")
    parser.set_defaults(write_aurora=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_worker_settings(argv)
    try:
        summary = run_evaluation_job(settings)
    except Exception as exc:
        logger.exception("Evaluation worker failed: %s", exc)
        failure = _failure_summary(settings, str(exc))
        try:
            _persist_run_state(
                settings=settings,
                summary_payload={"error": str(exc), "scope_metadata": settings.scope_metadata},
                status="failed",
                message=str(exc),
                started_at=datetime.fromisoformat(failure.started_at),
                completed_at=datetime.fromisoformat(failure.completed_at),
            )
        except Exception:  # pragma: no cover - best effort failure reporting
            logger.exception("Failed to persist evaluation failure state.")
        print(json.dumps(failure.model_dump(mode="json"), indent=2, sort_keys=True))
        return 1

    print(json.dumps(summary.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
