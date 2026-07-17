from __future__ import annotations

from types import SimpleNamespace

from rag.context_assembler import assemble_context
from rag.retrievers import _hit_to_doc
from rag.schemas import SourceDomain
from rag.source_urls import build_source_url


def test_hit_to_doc_maps_legacy_cpp_reference_to_canonical_domain() -> None:
    hit = SimpleNamespace(
        score=0.93,
        payload={
            "chunk_id": "chunk-1",
            "content": "std::vector reference",
            "category": "Guideline",
            "week": 0,
            "priority": 2,
            "source_domain": "cpp_reference",
            "source_type": "cppreference",
        },
    )

    doc = _hit_to_doc(hit, default_source_domain=SourceDomain.CPP_CORE_GUIDELINES)

    assert doc.source_domain is SourceDomain.CPP_CORE_GUIDELINES
    assert doc.content == "std::vector reference"
    assert doc.chunk_id == "chunk-1"


def test_build_source_url_maps_mit_files_to_real_ocw_pages() -> None:
    lecture = build_source_url(
        source_domain=SourceDomain.MIT_OCW_LECTURE,
        course_id="mit_2014",
        file_name="MIT6_S096IAP14_Lecture10.pdf",
    )
    assignment = build_source_url(
        source_domain=SourceDomain.MIT_OCW_LECTURE,
        course_id="mit_2014",
        file_name="MIT6_S096IAP14_ass1_p1.pdf",
    )
    assert lecture == (
        "https://ocw.mit.edu/courses/"
        "6-s096-effective-programming-in-c-and-c-january-iap-2014/pages/lecture-notes/"
    )
    assert assignment.endswith("/pages/assignments/")
    # The historically-hallucinated 404 shape must never be produced.
    assert "/resources/lectures-and-assignments/index.html" not in lecture
    assert "effective-programming" in lecture  # correct 2014 slug, not a guessed one


def test_hit_to_doc_populates_citation_url_and_context_emits_source_line() -> None:
    hit = SimpleNamespace(
        score=0.91,
        payload={
            "chunk_id": "c1",
            "content": "A reference is declared with & in the parameter type.",
            "category": "Pedagogical_Context",
            "week": 4,
            "priority": 2,
            "source_domain": "mit_ocw_lecture",
            "course_id": "mit_2014",
            "file_name": "MIT6_S096IAP14_Lecture4.pdf",
        },
    )
    doc = _hit_to_doc(hit)
    assert doc.file_name == "MIT6_S096IAP14_Lecture4.pdf"
    assert doc.source_url.endswith("/pages/lecture-notes/")

    context = assemble_context(
        syllabus=None, rules=[], pedagogical=[doc], supplementary=[], query_week=4
    )
    assert f"Source: {doc.source_url}" in context
