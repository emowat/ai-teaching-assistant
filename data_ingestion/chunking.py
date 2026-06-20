"""Helpers for turning parsed teacher-upload envelopes into indexable chunks.

The parser already produces normalized JSON envelopes. This module turns those
envelopes into stable ChunkPayload records and Qdrant payload dictionaries so
the ingestion worker can stay thin and testable.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from rag.loader import CATEGORY_PRIORITY, classify_category
from rag.schemas import ChunkPayload, DocCategory, SourceDomain

_CHUNK_NAMESPACE = uuid.UUID("4f2a6a9e-8c0c-42eb-95aa-4d0c781f3dc0")
_MAX_CONTENT_LENGTH = 4000


@dataclass(frozen=True)
class ChunkRecord:
    """A parsed-envelope block, its chunk payload, and the Qdrant payload."""

    index: int
    block: dict[str, Any]
    chunk: ChunkPayload
    payload: dict[str, Any]


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _coerce_text(value: object, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def load_parsed_envelope(path: str | Path) -> dict[str, Any]:
    """Load a parsed JSON envelope from disk."""
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))


def load_parsed_envelopes_from_dir(input_dir: str | Path) -> list[dict[str, Any]]:
    """Load every parsed JSON envelope in a directory tree."""
    root = Path(input_dir)
    envelopes: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        envelopes.append(load_parsed_envelope(path))
    return envelopes


def prepared_chunk_artifact_name(envelope: Mapping[str, Any]) -> str:
    """Return a deterministic artifact name for the prepared chunk JSON."""
    file_name = _coerce_text(envelope.get("file_name"), "envelope")
    document_id = _coerce_text(envelope.get("document_id"), "document")
    file_type = _coerce_text(envelope.get("file_type"), "json")
    stem = Path(file_name).stem or "envelope"
    return f"{stem}__{document_id[:8]}__{file_type}__chunks.json"


def _stable_chunk_id(document_id: str, block_id: str, content: str) -> str:
    """Return a deterministic UUID for the given document block."""
    normalized = "::".join((document_id, block_id, content[:500]))
    return str(uuid.uuid5(_CHUNK_NAMESPACE, normalized))


def _source_domain_for_course(course_id: str) -> SourceDomain:
    course = course_id.strip().lower()
    if course == "cs50":
        return SourceDomain.HARVARD_CS50
    return SourceDomain.MIT_OCW_LECTURE


def _classify_teacher_upload(
    *,
    file_name: str,
    text: str,
    has_code: bool,
) -> DocCategory:
    lower_name = file_name.lower()
    if "syllabus" in lower_name:
        return DocCategory.SYLLABUS
    if "assignment" in lower_name and "solution" in lower_name:
        return DocCategory.SUPPLEMENTARY
    return classify_category(text, has_code, source="lecture")


def build_qdrant_payload(
    *,
    envelope: Mapping[str, Any],
    block: Mapping[str, Any],
    chunk: ChunkPayload,
    block_index: int,
) -> dict[str, Any]:
    """Build the Qdrant payload for a chunk while preserving provenance."""
    payload = chunk.model_dump(mode="json")
    payload.update(
        {
            "document_id": _coerce_text(envelope.get("document_id"), ""),
            "course_id": _coerce_text(envelope.get("course_id"), ""),
            "source_s3_uri": _coerce_text(envelope.get("source_s3_uri"), ""),
            "parsed_s3_uri": _coerce_text(envelope.get("parsed_s3_uri"), ""),
            "file_name": _coerce_text(envelope.get("file_name"), ""),
            "file_type": _coerce_text(envelope.get("file_type"), ""),
            "parser_version": _coerce_text(envelope.get("parser_version"), ""),
            "created_at": _coerce_text(envelope.get("created_at"), ""),
            "envelope_metadata": envelope.get("metadata", {}),
            "block_index": block_index,
            "block_id": _coerce_text(block.get("block_id"), f"block_{block_index}"),
            "block_type": _coerce_text(block.get("block_type"), ""),
            "heading": _coerce_text(block.get("heading"), ""),
            "slide_number": _coerce_int(block.get("slide_number"), default=0) or None,
            "page_number": _coerce_int(block.get("page_number"), default=0) or None,
        }
    )
    return payload


def build_chunk_records_from_envelope(
    envelope: Mapping[str, Any],
) -> list[ChunkRecord]:
    """Convert a parsed envelope into stable chunk records."""
    document_id = _coerce_text(envelope.get("document_id"), "")
    course_id = _coerce_text(envelope.get("course_id"), "")
    file_name = _coerce_text(envelope.get("file_name"), "document")
    file_type = _coerce_text(envelope.get("file_type"), "section")
    metadata = envelope.get("metadata", {})
    blocks = envelope.get("blocks", [])
    week = 0
    if isinstance(metadata, Mapping):
        week = _coerce_int(metadata.get("week"), default=0)
    source_domain = _source_domain_for_course(course_id)

    records: list[ChunkRecord] = []
    for index, raw_block in enumerate(blocks):
        if not isinstance(raw_block, Mapping):
            continue

        text = _coerce_text(raw_block.get("text"), "")
        if not text:
            continue

        heading = _coerce_text(raw_block.get("heading"), "")
        block_id = _coerce_text(raw_block.get("block_id"), f"block_{index}")
        has_code = bool(raw_block.get("has_code", False))
        category = _classify_teacher_upload(
            file_name=file_name,
            text=text,
            has_code=has_code,
        )
        content = f"[{heading}] {text}" if heading else text
        content = content[:_MAX_CONTENT_LENGTH]
        chunk_id = _stable_chunk_id(document_id, block_id, content)
        topic = heading.lower().replace(" ", "_") if heading else file_type

        chunk = ChunkPayload(
            chunk_id=chunk_id,
            content=content,
            week=week,
            category=category,
            topic=topic,
            priority=CATEGORY_PRIORITY.get(category, 2),
            source_domain=source_domain,
            source_type=f"teacher_upload_{file_type}",
            page_number=_coerce_int(raw_block.get("page_number"), default=0) or None,
        )
        payload = build_qdrant_payload(
            envelope=envelope,
            block=raw_block,
            chunk=chunk,
            block_index=index,
        )
        records.append(
            ChunkRecord(
                index=index,
                block=dict(raw_block),
                chunk=chunk,
                payload=payload,
            )
        )

    return records


def build_chunks_from_envelope(
    envelope: Mapping[str, Any],
) -> list[ChunkPayload]:
    """Return only the ChunkPayload values for a parsed envelope."""
    return [record.chunk for record in build_chunk_records_from_envelope(envelope)]


def build_prepared_chunk_document(
    *,
    envelope: Mapping[str, Any],
    records: list[ChunkRecord],
) -> dict[str, Any]:
    """Build a human-readable artifact describing the prepared chunks."""
    return {
        "document_id": _coerce_text(envelope.get("document_id"), ""),
        "course_id": _coerce_text(envelope.get("course_id"), ""),
        "source_s3_uri": _coerce_text(envelope.get("source_s3_uri"), ""),
        "parsed_s3_uri": _coerce_text(envelope.get("parsed_s3_uri"), ""),
        "file_name": _coerce_text(envelope.get("file_name"), ""),
        "file_type": _coerce_text(envelope.get("file_type"), ""),
        "parser_version": _coerce_text(envelope.get("parser_version"), ""),
        "created_at": _coerce_text(envelope.get("created_at"), ""),
        "metadata": envelope.get("metadata", {}),
        "chunk_count": len(records),
        "chunks": [record.payload for record in records],
    }
