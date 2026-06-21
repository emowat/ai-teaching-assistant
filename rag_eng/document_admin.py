"""S3-backed document admin helpers for the `rag_eng` service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from dotenv import load_dotenv

from rag_eng.course_admin import CourseNotFoundError
from rag_eng.schemas import (
    AdminCourseCorpusVersion,
    AdminCourseDocument,
    AdminCourseDocumentListResponse,
    AdminCourseDocumentUploadRequest,
    AdminCourseDocumentUploadResponse,
)


load_dotenv()


@dataclass(frozen=True)
class DocumentAdminRuntimeConfig:
    """Runtime settings for document admin endpoints."""

    database_url: str | None
    s3_data_bucket: str
    aws_region: str
    aws_profile: str | None
    connect_timeout_seconds: int
    presign_expiry_seconds: int


@dataclass(frozen=True)
class CourseStorageLayout:
    """Stable S3 prefixes used for a course ingestion workflow."""

    upload_prefix: str
    parsed_prefix: str
    prepared_prefix: str


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


def _connect_postgres(database_url: str, connect_timeout_seconds: int):
    """Create a psycopg connection lazily so tests can stub it."""
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - exercised only when missing
        raise RuntimeError("psycopg is required for document admin operations.") from exc

    return psycopg.connect(database_url, connect_timeout=connect_timeout_seconds)


def load_document_admin_runtime_config(
    env: Mapping[str, str] | None = None,
) -> DocumentAdminRuntimeConfig:
    """Load S3/document admin settings from the process environment."""
    source = env or os.environ
    return DocumentAdminRuntimeConfig(
        database_url=(
            source.get("COURSE_REGISTRY_DATABASE_URL")
            or source.get("INGESTION_JOBS_DATABASE_URL")
            or source.get("DATABASE_URL")
        ),
        s3_data_bucket=source.get("S3_DATA_BUCKET", "codingrabbit-data-dev").strip(),
        aws_region=source.get(
            "AWS_REGION",
            source.get("AWS_DEFAULT_REGION", "us-east-1"),
        ).strip(),
        aws_profile=source.get("AWS_PROFILE") or None,
        connect_timeout_seconds=int(
            source.get(
                "COURSE_REGISTRY_CONNECT_TIMEOUT_SECONDS",
                source.get("INGESTION_JOBS_CONNECT_TIMEOUT_SECONDS", "5"),
            )
        ),
        presign_expiry_seconds=int(
            source.get("DOCUMENT_UPLOAD_PRESIGN_TTL_SECONDS", "900")
        ),
    )


def _build_s3_client(runtime: DocumentAdminRuntimeConfig):
    import boto3

    session = boto3.Session(
        profile_name=runtime.aws_profile,
        region_name=runtime.aws_region,
    )
    return session.client("s3")


def build_course_storage_layout(course_id: str) -> CourseStorageLayout:
    """Return the stable ingestion prefixes for a course."""
    normalized = course_id.strip()
    return CourseStorageLayout(
        upload_prefix=f"teacher_uploads/{normalized}/",
        parsed_prefix=f"parsed_json/{normalized}/",
        prepared_prefix=f"prepared_chunks/{normalized}/",
    )


def _require_course_exists(connection, course_id: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT course_id
            FROM courses
            WHERE course_id = %s
            """,
            (course_id,),
        )
        row = cursor.fetchone()
    if row is None:
        raise CourseNotFoundError(f"Course not found: {course_id}")


def _list_s3_objects(client, *, bucket: str, prefix: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    continuation_token: str | None = None

    while True:
        params: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if continuation_token:
            params["ContinuationToken"] = continuation_token
        response = client.list_objects_v2(**params)
        objects.extend(response.get("Contents", []) or [])
        if not response.get("IsTruncated"):
            break
        continuation_token = response.get("NextContinuationToken")
        if not continuation_token:
            break

    return objects


def list_admin_course_documents(
    course_id: str,
    *,
    runtime: DocumentAdminRuntimeConfig | None = None,
    s3_client=None,
) -> AdminCourseDocumentListResponse:
    """List uploaded source documents for a course from S3."""
    runtime = runtime or load_document_admin_runtime_config()
    if not runtime.database_url:
        raise RuntimeError("Course registry database URL is not configured.")

    with _connect_postgres(
        runtime.database_url,
        runtime.connect_timeout_seconds,
    ) as connection:
        _require_course_exists(connection, course_id)

    layout = build_course_storage_layout(course_id)
    client = s3_client or _build_s3_client(runtime)
    objects = _list_s3_objects(
        client,
        bucket=runtime.s3_data_bucket,
        prefix=layout.upload_prefix,
    )

    documents: list[AdminCourseDocument] = []
    for item in objects:
        key = str(item.get("Key") or "")
        if not key or key.endswith("/"):
            continue
        documents.append(
            AdminCourseDocument(
                key=key,
                file_name=key.rsplit("/", 1)[-1],
                size_bytes=int(item.get("Size") or 0),
                last_modified=_format_timestamp(item.get("LastModified")),
                etag=str(item.get("ETag")) if item.get("ETag") is not None else None,
            )
        )

    documents.sort(
        key=lambda document: (document.last_modified, document.file_name),
        reverse=True,
    )

    return AdminCourseDocumentListResponse(
        course_id=course_id,
        bucket=runtime.s3_data_bucket,
        upload_prefix=layout.upload_prefix,
        parsed_prefix=layout.parsed_prefix,
        prepared_prefix=layout.prepared_prefix,
        documents=documents,
    )


def create_admin_course_upload_url(
    course_id: str,
    request: AdminCourseDocumentUploadRequest,
    *,
    runtime: DocumentAdminRuntimeConfig | None = None,
    s3_client=None,
) -> AdminCourseDocumentUploadResponse:
    """Create a presigned PUT URL for a course document upload."""
    runtime = runtime or load_document_admin_runtime_config()
    if not runtime.database_url:
        raise RuntimeError("Course registry database URL is not configured.")

    with _connect_postgres(
        runtime.database_url,
        runtime.connect_timeout_seconds,
    ) as connection:
        _require_course_exists(connection, course_id)

    layout = build_course_storage_layout(course_id)
    key = f"{layout.upload_prefix}{request.file_name}"
    headers: dict[str, str] = {}
    params: dict[str, Any] = {
        "Bucket": runtime.s3_data_bucket,
        "Key": key,
    }
    if request.content_type:
        headers["Content-Type"] = request.content_type
        params["ContentType"] = request.content_type

    client = s3_client or _build_s3_client(runtime)
    upload_url = client.generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=runtime.presign_expiry_seconds,
    )

    return AdminCourseDocumentUploadResponse(
        course_id=course_id,
        bucket=runtime.s3_data_bucket,
        key=key,
        upload_prefix=layout.upload_prefix,
        parsed_prefix=layout.parsed_prefix,
        prepared_prefix=layout.prepared_prefix,
        upload_url=upload_url,
        expires_in_seconds=runtime.presign_expiry_seconds,
        required_headers=headers,
    )


def list_admin_course_corpus_versions(
    course_id: str,
    *,
    limit: int = 25,
    runtime: DocumentAdminRuntimeConfig | None = None,
) -> list[AdminCourseCorpusVersion]:
    """List Aurora-backed corpus versions for a course."""
    runtime = runtime or load_document_admin_runtime_config()
    if not runtime.database_url:
        raise RuntimeError("Course registry database URL is not configured.")

    with _connect_postgres(
        runtime.database_url,
        runtime.connect_timeout_seconds,
    ) as connection:
        _require_course_exists(connection, course_id)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
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
                  metadata,
                  created_at,
                  updated_at,
                  started_at,
                  completed_at
                FROM course_corpus_versions
                WHERE course_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (course_id, limit),
            )
            rows = cursor.fetchall()

    versions: list[AdminCourseCorpusVersion] = []
    for row in rows:
        (
            course_corpus_version_id,
            stored_course_id,
            collection_name,
            source_bucket,
            source_prefix,
            parsed_prefix,
            prepared_prefix,
            status,
            active,
            recreate_collection,
            metadata,
            created_at,
            updated_at,
            started_at,
            completed_at,
        ) = row
        versions.append(
            AdminCourseCorpusVersion(
                course_corpus_version_id=str(course_corpus_version_id),
                course_id=str(stored_course_id),
                collection_name=str(collection_name),
                source_bucket=str(source_bucket),
                source_prefix=str(source_prefix),
                parsed_prefix=(
                    str(parsed_prefix) if parsed_prefix is not None else None
                ),
                prepared_prefix=(
                    str(prepared_prefix) if prepared_prefix is not None else None
                ),
                status=str(status),
                active=bool(active),
                recreate_collection=bool(recreate_collection),
                metadata=dict(metadata or {}),
                created_at=_format_timestamp(created_at),
                updated_at=_format_timestamp(updated_at),
                started_at=_format_timestamp(started_at) or None,
                completed_at=_format_timestamp(completed_at) or None,
            )
        )

    return versions
