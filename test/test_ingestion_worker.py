from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from data_ingestion.chunking import (
    build_chunk_records_from_envelope,
    prepared_chunk_artifact_name,
)
from data_ingestion.ingestion_worker import ChunkIndexSummary, main, run_chunk_index
from rag.schemas import DocCategory, SourceDomain


def _sample_envelope() -> dict[str, object]:
    return {
        "document_id": "doc-123",
        "course_id": "cs50",
        "source_s3_uri": "s3://bucket/teacher_uploads/cs50/lecture_1.pdf",
        "parsed_s3_uri": "s3://bucket/parsed_json/cs50/lecture_1__pdf.json",
        "file_name": "lecture_1.pdf",
        "file_type": "pdf",
        "parser_version": "teacher_parser_v1",
        "created_at": "2026-06-19T00:00:00+00:00",
        "metadata": {"page_count": 2, "block_count": 2, "week": 4},
        "blocks": [
            {
                "block_id": "page_1",
                "block_type": "page",
                "page_number": 1,
                "slide_number": None,
                "heading": "Intro",
                "text": "Never do this.",
                "has_code": False,
            },
            {
                "block_id": "page_2",
                "block_type": "page",
                "page_number": 2,
                "slide_number": None,
                "heading": "Pointers",
                "text": "A pointer stores an address.",
                "has_code": True,
            },
        ],
    }


def test_build_chunk_records_from_envelope_preserves_provenance() -> None:
    envelope = _sample_envelope()

    records = build_chunk_records_from_envelope(envelope)
    repeated = build_chunk_records_from_envelope(envelope)

    assert len(records) == 2
    assert [record.chunk.chunk_id for record in records] == [
        record.chunk.chunk_id for record in repeated
    ]
    assert records[0].chunk.week == 4
    assert records[0].chunk.category == DocCategory.STRICT_RULES
    assert records[0].chunk.source_domain == SourceDomain.HARVARD_CS50
    assert records[1].chunk.category == DocCategory.PEDAGOGICAL_CONTEXT
    assert records[0].payload["document_id"] == "doc-123"
    assert records[0].payload["course_id"] == "cs50"
    assert records[0].payload["file_type"] == "pdf"
    assert records[0].payload["source_s3_uri"].startswith("s3://bucket/")


def test_prepared_chunk_artifact_name_is_stable() -> None:
    envelope = _sample_envelope()

    assert prepared_chunk_artifact_name(envelope).startswith("lecture_1__doc-123")
    assert prepared_chunk_artifact_name(envelope).endswith("__pdf__chunks.json")


class _FakeClient:
    def __init__(self) -> None:
        self.collections: list[dict[str, object]] = []
        self.payload_indexes: list[dict[str, object]] = []
        self.upserts: list[dict[str, object]] = []
        self.closed = False

    def collection_exists(self, name: str) -> bool:
        return bool(self.collections) and self.collections[0]["collection_name"] == name

    def create_collection(self, **kwargs) -> None:
        self.collections.append(kwargs)

    def create_payload_index(self, **kwargs) -> None:
        self.payload_indexes.append(kwargs)

    def upsert(self, **kwargs) -> None:
        self.upserts.append(kwargs)

    def close(self) -> None:
        self.closed = True


class _FakeModel:
    def encode(self, text: str):
        return [float(len(text)), 1.0, 2.0]


def test_run_chunk_index_indexes_local_envelopes(tmp_path: Path) -> None:
    input_dir = tmp_path / "parsed"
    output_dir = tmp_path / "prepared"
    input_dir.mkdir()

    envelope = _sample_envelope()
    (input_dir / "lecture_1__pdf.json").write_text(
        json.dumps(envelope, indent=2),
        encoding="utf-8",
    )

    args = Namespace(
        bucket=None,
        input_prefix=None,
        profile=None,
        region="us-east-1",
        local_input_dir=str(input_dir),
        course_id="cs50",
        collection_name="cs50_course",
        prepared_output_prefix=None,
        local_output_dir=str(output_dir),
        embedding_model="fake-model",
        dry_run=False,
        recreate_collection=False,
    )

    client = _FakeClient()
    model = _FakeModel()

    summary = run_chunk_index(args, client=client, model=model)

    assert isinstance(summary, ChunkIndexSummary)
    assert summary.collection_name == "cs50_course"
    assert summary.envelopes_processed == 1
    assert summary.chunks_indexed == 2
    assert summary.created_collection is True
    assert summary.prepared_artifacts_written == 1
    assert client.upserts
    assert output_dir.exists()
    assert any(path.name.endswith("__chunks.json") for path in output_dir.iterdir())


def test_main_chunk_index_reports_completion(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run_chunk_index(args, *, client=None, model=None):
        return ChunkIndexSummary(
            collection_name="cs50_course",
            envelopes_processed=1,
            chunks_indexed=2,
            created_collection=True,
            prepared_artifacts_written=1,
        )

    def fake_complete_ingestion_job(job_id, *, status, message, ecs_response=None):
        captured["job_id"] = job_id
        captured["status"] = status
        captured["message"] = message
        captured["ecs_response"] = ecs_response
        return True

    monkeypatch.setenv("INGESTION_JOB_ID", "job-123")
    monkeypatch.setattr("data_ingestion.ingestion_worker.run_chunk_index", fake_run_chunk_index)
    monkeypatch.setattr(
        "data_ingestion.ingestion_worker.complete_ingestion_job",
        fake_complete_ingestion_job,
    )

    input_dir = tmp_path / "parsed"
    input_dir.mkdir()

    main(
        [
            "chunk-index",
            "--local-input-dir",
            str(input_dir),
            "--course-id",
            "cs50",
            "--collection-name",
            "cs50_course",
        ]
    )

    assert captured["job_id"] == "job-123"
    assert captured["status"] == "completed"
    assert "Indexed 2 chunk(s)" in captured["message"]
    assert captured["ecs_response"]["collection_name"] == "cs50_course"
