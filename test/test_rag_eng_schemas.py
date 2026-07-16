from __future__ import annotations

import pytest
from pydantic import ValidationError

from rag_eng.schemas import (
    AdminSection,
    AdminSectionCreate,
    AdminSectionMembershipCreate,
    AdminCourseAliasCreate,
    AdminCourseCreate,
    AdminCourseDocumentUploadRequest,
    AdminCourseUpdate,
    AdminUser,
    AdminUserCreate,
    EvaluationRunCreate,
    EvaluationRunSummary,
    QueryPayload,
    QueryRequest,
    QueryResponse,
    QueryResult,
)
from rag.schemas import RetrievalResult


def test_query_payload_defaults_result_count() -> None:
    """QueryPayload should supply the documented default result count."""
    payload = QueryPayload(
        student_message="Why does this crash?",
        week=3,
    )

    assert payload.result_count == 8
    assert payload.course_id is None
    assert payload.session_id is None
    assert QueryPayload.model_json_schema()["examples"]


def test_query_payload_accepts_explicit_course_id() -> None:
    """QueryPayload should accept explicit course routing metadata."""
    payload = QueryPayload(
        student_message="Why does this crash?",
        week=3,
        course_id="mit14",
    )

    assert payload.course_id == "mit14"


@pytest.mark.parametrize("result_count", [1, 10, 20])
def test_query_payload_accepts_valid_result_counts(result_count: int) -> None:
    """Valid result_count values should pass Pydantic validation."""
    payload = QueryPayload(
        student_message="Why does this crash?",
        week=3,
        result_count=result_count,
    )

    assert payload.result_count == result_count


@pytest.mark.parametrize("result_count", [0, -1, 21])
def test_query_payload_rejects_invalid_result_counts(result_count: int) -> None:
    """Out-of-range result_count values should fail validation."""
    with pytest.raises(ValidationError):
        QueryPayload(
            student_message="Why does this crash?",
            week=3,
            result_count=result_count,
        )


def test_query_request_alias_matches_query_payload() -> None:
    """QueryRequest should remain a compatibility alias for the payload model."""
    request = QueryRequest(
        student_message="Why does this crash?",
        week=3,
    )

    assert request.result_count == 8


def test_query_result_schema_exposes_examples() -> None:
    """QueryResult should expose schema examples for the OpenAPI docs."""
    assert QueryResult.model_json_schema()["examples"]


def test_query_response_serializes_nested_retrieval_result() -> None:
    """QueryResponse should serialize nested retrieval results cleanly."""
    response = QueryResponse(
        answer="Check the pointer before dereferencing it.",
        retrieval_result=RetrievalResult(
            formatted_context="[Pedagogical_Context]\nPointers"
        ),
        formatted_context="[Pedagogical_Context]\nPointers",
        session_id="session-1",
        request_id="request-1",
        turn_id="turn-1",
        turn_index=1,
    )

    dumped = response.model_dump()

    assert dumped["answer"]
    assert dumped["formatted_context"]
    assert dumped["session_id"] == "session-1"
    assert dumped["turn_index"] == 1
    assert (
        dumped["retrieval_result"]["formatted_context"]
        == "[Pedagogical_Context]\nPointers"
    )


def test_admin_course_create_schema_parses_course_source() -> None:
    course = AdminCourseCreate(
        course_id="cs202",
        display_name="Advanced C++",
        course_source="mit14",
        collection_name="course_cs202",
    )

    assert course.course_source.value == "mit14"
    assert course.is_active is True


def test_admin_course_update_requires_at_least_one_field() -> None:
    with pytest.raises(ValidationError):
        AdminCourseUpdate()


def test_admin_course_alias_create_requires_one_alias() -> None:
    with pytest.raises(ValidationError):
        AdminCourseAliasCreate(aliases=[])


def test_admin_course_document_upload_request_rejects_nested_paths() -> None:
    with pytest.raises(ValidationError):
        AdminCourseDocumentUploadRequest(file_name="slides/week1.pdf")


def test_admin_course_document_upload_request_trims_fields() -> None:
    request = AdminCourseDocumentUploadRequest(
        file_name="  lecture-01.pdf  ",
        content_type="  application/pdf  ",
    )

    assert request.file_name == "lecture-01.pdf"
    assert request.content_type == "application/pdf"


def test_admin_user_and_section_models_validate_defaults() -> None:
    user = AdminUserCreate(
        email="prof@example.edu",
        display_name="Prof",
        primary_role="professor",
    )
    section = AdminSectionCreate(
        section_id="mit14-fall-001",
        course_id="mit14",
        display_name="MIT 6.0014 Section A",
    )
    membership = AdminSectionMembershipCreate(
        user_id="user-1",
        role_in_section="professor",
    )

    assert user.status == "invited"
    assert section.is_active is True
    assert membership.user_id == "user-1"

    admin_user = AdminUser(
        user_id="user-1",
        cognito_sub="sub-1",
        email="prof@example.edu",
        display_name="Prof",
        primary_role="professor",
        status="active",
        created_at="2026-06-20T00:00:00+00:00",
        updated_at="2026-06-20T00:00:00+00:00",
        section_memberships=[],
    )
    admin_section = AdminSection(
        section_id="mit14-fall-001",
        course_id="mit14",
        course_display_name="MIT 6.0014",
        display_name="MIT 6.0014 Section A",
        term="Fall 2026",
        memberships=[],
    )

    assert admin_user.primary_role == "professor"
    assert admin_section.course_id == "mit14"


def test_evaluation_run_create_requires_dataset_source() -> None:
    with pytest.raises(ValidationError):
        EvaluationRunCreate(
            judge_provider="openai",
            judge_model="gpt-4o-mini",
        )


def test_evaluation_run_summary_serializes_nested_artifacts_and_metrics() -> None:
    summary = EvaluationRunSummary(
        evaluation_run_id="eval-1",
        run_label="Week 1 smoke",
        judge_provider="openai",
        judge_model="gpt-4o-mini",
        status="queued",
        artifacts=[],
        metrics=[],
    )

    dumped = summary.model_dump()

    assert dumped["evaluation_run_id"] == "eval-1"
    assert dumped["judge_provider"] == "openai"
    assert dumped["status"] == "queued"
