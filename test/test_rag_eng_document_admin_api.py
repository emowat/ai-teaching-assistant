from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rag_eng.api import create_app
from rag_eng.auth.models import CurrentUser
from rag_eng.course_admin import CourseNotFoundError
from rag_eng.schemas import (
    AdminCourseCorpusVersion,
    AdminCourseDocument,
    AdminCourseDocumentDeleteResponse,
    AdminCourseDocumentListResponse,
    AdminCourseDocumentUploadResponse,
    IngestionJobResponse,
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _documents_response() -> AdminCourseDocumentListResponse:
    return AdminCourseDocumentListResponse(
        course_id="mit20",
        bucket="codingrabbit-data-dev",
        upload_prefix="teacher_uploads/mit20/",
        parsed_prefix="parsed_json/mit20/",
        prepared_prefix="prepared_chunks/mit20/",
        documents=[
            AdminCourseDocument(
                key="teacher_uploads/mit20/syllabus.pdf",
                file_name="syllabus.pdf",
                size_bytes=1024,
                last_modified="2026-06-21T00:00:00+00:00",
                etag='"etag-1"',
            )
        ],
    )


def _upload_response() -> AdminCourseDocumentUploadResponse:
    return AdminCourseDocumentUploadResponse(
        course_id="mit20",
        bucket="codingrabbit-data-dev",
        key="teacher_uploads/mit20/syllabus.pdf",
        upload_prefix="teacher_uploads/mit20/",
        parsed_prefix="parsed_json/mit20/",
        prepared_prefix="prepared_chunks/mit20/",
        upload_url="https://example.test/upload",
        expires_in_seconds=900,
        required_headers={"Content-Type": "application/pdf"},
    )


def _delete_response() -> AdminCourseDocumentDeleteResponse:
    return AdminCourseDocumentDeleteResponse(
        course_id="mit20",
        bucket="codingrabbit-data-dev",
        key="teacher_uploads/mit20/syllabus.pdf",
        deleted=True,
    )


def _corpus_version() -> AdminCourseCorpusVersion:
    return AdminCourseCorpusVersion(
        course_corpus_version_id="version-1",
        course_id="mit20",
        collection_name="course_mit20",
        source_bucket="codingrabbit-data-dev",
        source_prefix="teacher_uploads/mit20/",
        parsed_prefix="parsed_json/mit20/",
        prepared_prefix="prepared_chunks/mit20/",
        status="completed",
        active=True,
        recreate_collection=False,
        metadata={"message": "Indexed 12 chunk(s)."},
        created_at="2026-06-21T00:00:00+00:00",
        updated_at="2026-06-21T00:01:00+00:00",
        started_at="2026-06-21T00:00:10+00:00",
        completed_at="2026-06-21T00:01:00+00:00",
    )


def _ingestion_job() -> IngestionJobResponse:
    return IngestionJobResponse(
        job_id="job-1",
        course_id="mit20",
        job_kind="parse",
        status="completed",
        message="Parsed envelopes written successfully.",
        registered=True,
        course_corpus_version_id=None,
        ecs_cluster="cluster",
        ecs_task_definition="taskdef",
        ecs_container_name="worker",
        ecs_task_arn="arn:aws:ecs:task/123",
        collection_name="course_mit20",
        bucket="codingrabbit-data-dev",
        input_prefix="teacher_uploads/mit20/",
        output_prefix="parsed_json/mit20/",
        prepared_output_prefix=None,
        request_payload={
            "job_id": "job-1",
            "course_id": "mit20",
            "job_kind": "parse",
            "bucket": "codingrabbit-data-dev",
            "input_prefix": "teacher_uploads/mit20/",
            "output_prefix": "parsed_json/mit20/",
            "collection_name": "course_mit20",
            "recreate_collection": False,
        },
        ecs_response={},
        created_at="2026-06-21T00:00:00+00:00",
        updated_at="2026-06-21T00:01:00+00:00",
        started_at="2026-06-21T00:00:10+00:00",
        completed_at="2026-06-21T00:01:00+00:00",
    )


def test_admin_course_documents_allow_authorized_request(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.list_admin_course_documents",
        lambda course_id: _documents_response(),
    )

    response = client.get(
        "/admin/courses/mit20/documents",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert response.status_code == 200
    assert response.json()["documents"][0]["file_name"] == "syllabus.pdf"


def test_admin_course_document_upload_url_allows_admin_bearer_request(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.create_admin_course_upload_url",
        lambda course_id, payload: _upload_response(),
    )

    def _admin(_token: str, _settings) -> CurrentUser:
        return CurrentUser(
            cognito_sub="admin-sub-1",
            email="admin@test.codingrabbit.dev",
            groups=["Admins"],
            primary_role="admin",
        )

    monkeypatch.setattr("rag_eng.api.verify_cognito_access_token", _admin)

    response = client.post(
        "/admin/courses/mit20/documents/upload-url",
        headers={"Authorization": "Bearer valid-token"},
        json={
            "file_name": "syllabus.pdf",
            "content_type": "application/pdf",
        },
    )

    assert response.status_code == 200
    assert response.json()["required_headers"]["Content-Type"] == "application/pdf"


def test_admin_course_document_delete_allows_authorized_request(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.delete_admin_course_document",
        lambda course_id, key: _delete_response(),
    )

    response = client.delete(
        "/admin/courses/mit20/documents?key=teacher_uploads%2Fmit20%2Fsyllabus.pdf",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert response.json()["key"] == "teacher_uploads/mit20/syllabus.pdf"


def test_admin_course_corpus_versions_map_missing_course_to_404(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.list_admin_course_corpus_versions",
        lambda course_id, limit=25: (_ for _ in ()).throw(
            CourseNotFoundError("missing")
        ),
    )

    response = client.get(
        "/admin/courses/missing/corpus-versions",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert response.status_code == 404


def test_admin_list_ingestion_jobs_allows_authorized_request(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.list_ingestion_jobs",
        lambda course_id=None, limit=25: [_ingestion_job()],
    )

    response = client.get(
        "/admin/ingestion/jobs?course_id=mit20&limit=10",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert response.status_code == 200
    assert response.json()[0]["course_id"] == "mit20"
    assert response.json()[0]["job_id"] == "job-1"


def test_admin_course_corpus_versions_allow_authorized_request(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.list_admin_course_corpus_versions",
        lambda course_id, limit=25: [_corpus_version()],
    )

    response = client.get(
        "/admin/courses/mit20/corpus-versions",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert response.status_code == 200
    assert response.json()[0]["course_corpus_version_id"] == "version-1"
