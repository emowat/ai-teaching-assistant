from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

import rag_eng.document_admin as document_admin
from rag_eng.course_admin import CourseNotFoundError
from rag_eng.schemas import AdminCourseDocumentUploadRequest

NOW = datetime(2026, 6, 21, tzinfo=timezone.utc)


@dataclass
class _FakeState:
    courses: dict[str, dict[str, object]]
    corpus_versions: list[dict[str, object]]


class _FakeCursor:
    def __init__(self, state: _FakeState):
        self.state = state
        self._rows: list[tuple[object, ...]] = []

    @staticmethod
    def _normalize_sql(query: str) -> str:
        return " ".join(query.split())

    def execute(self, query: str, params: tuple[object, ...] | None = None) -> None:
        sql = self._normalize_sql(query)
        params = params or ()

        if sql.startswith("SELECT course_id FROM courses WHERE course_id = %s"):
            course_id = str(params[0])
            record = self.state.courses.get(course_id)
            self._rows = [(record["course_id"],)] if record is not None else []
            return

        if sql.startswith(
            "SELECT course_corpus_version_id, course_id, collection_name, source_bucket, source_prefix, parsed_prefix, prepared_prefix, status, active, recreate_collection, metadata, created_at, updated_at, started_at, completed_at FROM course_corpus_versions WHERE course_id = %s ORDER BY created_at DESC LIMIT %s"
        ):
            course_id = str(params[0])
            limit = int(params[1])
            rows = [
                (
                    record["course_corpus_version_id"],
                    record["course_id"],
                    record["collection_name"],
                    record["source_bucket"],
                    record["source_prefix"],
                    record["parsed_prefix"],
                    record["prepared_prefix"],
                    record["status"],
                    record["active"],
                    record["recreate_collection"],
                    record["metadata"],
                    record["created_at"],
                    record["updated_at"],
                    record["started_at"],
                    record["completed_at"],
                )
                for record in self.state.corpus_versions
                if str(record["course_id"]) == course_id
            ]
            self._rows = rows[:limit]
            return

        raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, state: _FakeState):
        self.state = state

    def cursor(self):
        return _FakeCursor(self.state)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeS3Client:
    def __init__(self, objects: list[dict[str, object]] | None = None):
        self.objects = objects or []
        self.presign_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []

    def list_objects_v2(self, **kwargs):
        return {
            "Contents": list(self.objects),
            "IsTruncated": False,
        }

    def generate_presigned_url(self, method_name: str, *, Params, ExpiresIn: int):
        self.presign_calls.append(
            {
                "method_name": method_name,
                "params": dict(Params),
                "expires_in": ExpiresIn,
            }
        )
        return f"https://example.test/upload/{Params['Key']}"

    def delete_object(self, **kwargs):
        self.delete_calls.append(dict(kwargs))
        return {}


def _runtime() -> document_admin.DocumentAdminRuntimeConfig:
    return document_admin.DocumentAdminRuntimeConfig(
        database_url="postgresql://example",
        s3_data_bucket="codingrabbit-data-dev",
        aws_region="us-east-1",
        aws_profile="codingrabbit-dev",
        connect_timeout_seconds=5,
        presign_expiry_seconds=900,
    )


def _patch_connection(monkeypatch: pytest.MonkeyPatch, state: _FakeState) -> None:
    monkeypatch.setattr(
        document_admin,
        "_connect_postgres",
        lambda database_url, connect_timeout_seconds: _FakeConnection(state),
    )


def test_list_admin_course_documents_returns_layout_and_sorted_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _FakeState(
        courses={"mit20": {"course_id": "mit20"}},
        corpus_versions=[],
    )
    _patch_connection(monkeypatch, state)
    s3_client = _FakeS3Client(
        objects=[
            {
                "Key": "teacher_uploads/mit20/notes-week1.pdf",
                "Size": 2048,
                "LastModified": NOW,
                "ETag": '"abc123"',
            },
            {
                "Key": "teacher_uploads/mit20/",
                "Size": 0,
                "LastModified": NOW,
            },
            {
                "Key": "teacher_uploads/mit20/syllabus.pdf",
                "Size": 1024,
                "LastModified": datetime(2026, 6, 20, tzinfo=timezone.utc),
                "ETag": '"def456"',
            },
        ]
    )

    response = document_admin.list_admin_course_documents(
        "mit20",
        runtime=_runtime(),
        s3_client=s3_client,
    )

    assert response.course_id == "mit20"
    assert response.bucket == "codingrabbit-data-dev"
    assert response.upload_prefix == "teacher_uploads/mit20/"
    assert response.parsed_prefix == "parsed_json/mit20/"
    assert response.prepared_prefix == "prepared_chunks/mit20/"
    assert [document.file_name for document in response.documents] == [
        "notes-week1.pdf",
        "syllabus.pdf",
    ]


def test_create_admin_course_upload_url_returns_presigned_put_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _FakeState(
        courses={"mit20": {"course_id": "mit20"}},
        corpus_versions=[],
    )
    _patch_connection(monkeypatch, state)
    s3_client = _FakeS3Client()

    response = document_admin.create_admin_course_upload_url(
        "mit20",
        AdminCourseDocumentUploadRequest(
            file_name="lecture-01.pdf",
            content_type="application/pdf",
        ),
        runtime=_runtime(),
        s3_client=s3_client,
    )

    assert response.key == "teacher_uploads/mit20/lecture-01.pdf"
    assert response.required_headers == {"Content-Type": "application/pdf"}
    assert response.upload_url.endswith("/teacher_uploads/mit20/lecture-01.pdf")
    assert s3_client.presign_calls == [
        {
            "method_name": "put_object",
            "params": {
                "Bucket": "codingrabbit-data-dev",
                "Key": "teacher_uploads/mit20/lecture-01.pdf",
                "ContentType": "application/pdf",
            },
            "expires_in": 900,
        }
    ]


def test_list_admin_course_corpus_versions_returns_latest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _FakeState(
        courses={"mit20": {"course_id": "mit20"}},
        corpus_versions=[
            {
                "course_corpus_version_id": "version-2",
                "course_id": "mit20",
                "collection_name": "course_mit20",
                "source_bucket": "codingrabbit-data-dev",
                "source_prefix": "teacher_uploads/mit20/",
                "parsed_prefix": "parsed_json/mit20/",
                "prepared_prefix": "prepared_chunks/mit20/",
                "status": "completed",
                "active": True,
                "recreate_collection": False,
                "metadata": {"message": "Indexed 12 chunk(s)."},
                "created_at": NOW,
                "updated_at": NOW,
                "started_at": NOW,
                "completed_at": NOW,
            },
            {
                "course_corpus_version_id": "version-1",
                "course_id": "mit20",
                "collection_name": "course_mit20",
                "source_bucket": "codingrabbit-data-dev",
                "source_prefix": "teacher_uploads/mit20/",
                "parsed_prefix": "parsed_json/mit20/",
                "prepared_prefix": "prepared_chunks/mit20/",
                "status": "failed",
                "active": False,
                "recreate_collection": False,
                "metadata": {"message": "Failed."},
                "created_at": datetime(2026, 6, 20, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 6, 20, tzinfo=timezone.utc),
                "started_at": datetime(2026, 6, 20, tzinfo=timezone.utc),
                "completed_at": datetime(2026, 6, 20, tzinfo=timezone.utc),
            },
        ],
    )
    _patch_connection(monkeypatch, state)

    versions = document_admin.list_admin_course_corpus_versions(
        "mit20",
        runtime=_runtime(),
    )

    assert [version.course_corpus_version_id for version in versions] == [
        "version-2",
        "version-1",
    ]
    assert versions[0].metadata["message"] == "Indexed 12 chunk(s)."
    assert versions[0].active is True


def test_delete_admin_course_document_deletes_expected_s3_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _FakeState(
        courses={"mit20": {"course_id": "mit20"}},
        corpus_versions=[],
    )
    _patch_connection(monkeypatch, state)
    s3_client = _FakeS3Client()

    response = document_admin.delete_admin_course_document(
        "mit20",
        key="teacher_uploads/mit20/syllabus.pdf",
        runtime=_runtime(),
        s3_client=s3_client,
    )

    assert response.deleted is True
    assert response.key == "teacher_uploads/mit20/syllabus.pdf"
    assert s3_client.delete_calls == [
        {
            "Bucket": "codingrabbit-data-dev",
            "Key": "teacher_uploads/mit20/syllabus.pdf",
        }
    ]


def test_delete_admin_course_document_rejects_key_outside_course_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _FakeState(
        courses={"mit20": {"course_id": "mit20"}},
        corpus_versions=[],
    )
    _patch_connection(monkeypatch, state)

    with pytest.raises(ValueError, match="course upload prefix"):
        document_admin.delete_admin_course_document(
            "mit20",
            key="teacher_uploads/mit21/syllabus.pdf",
            runtime=_runtime(),
            s3_client=_FakeS3Client(),
        )


def test_list_admin_course_documents_rejects_unknown_course(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _FakeState(courses={}, corpus_versions=[])
    _patch_connection(monkeypatch, state)

    with pytest.raises(CourseNotFoundError):
        document_admin.list_admin_course_documents(
            "missing",
            runtime=_runtime(),
            s3_client=_FakeS3Client(),
        )
