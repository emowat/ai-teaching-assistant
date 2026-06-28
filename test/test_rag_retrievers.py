from __future__ import annotations

from types import SimpleNamespace

from rag.retrievers import _hit_to_doc
from rag.schemas import SourceDomain


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
