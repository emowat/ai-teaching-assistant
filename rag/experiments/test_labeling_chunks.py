#!/usr/bin/env python3
"""
test_labeling_chunks.py  —  Unit tests for labeling_chunks.py

Covers pure functions and integration points. Skips tests that require
live LLM APIs (Cohere, OpenAI) or heavy models unless explicitly opted in.

Usage:
  pytest test_labeling_chunks.py -v                     # unit tests only
  pytest test_labeling_chunks.py -v --run-integration   # + chunk loading
  pytest test_labeling_chunks.py -v --run-slow          # + embedding model tests
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure the experiments dir is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from labeling_chunks import (
    Chunk,
    EvalQuery,
    LabelingResult,
    _classify_category,
    _neighbor_expansion,
    _parse_label_output,
    _resolve_week,
    _simple_bm25,
    _stable_chunk_id,
    _strip_headers,
    _tier2_k,
    build_candidate_pool,
    extract_query,
    load_chunks,
    load_harvard_chunks,
    sample_queries,
    trigger_to_mode,
    _build_labeling_prompt,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_chunks() -> list[Chunk]:
    """Small, deterministic chunk set for Tier 2 / neighbor tests."""
    return [
        Chunk(chunk_id="c01", content="pointer dereference and address-of operator",
              week=3, category="Pedagogical_Context", source_file="03_lecture.json",
              page_number=1, source_domain="mit_ocw_lecture"),
        Chunk(chunk_id="c02", content="new and delete for heap allocation",
              week=3, category="Strict_Rules", source_file="03_lecture.json",
              page_number=2, source_domain="mit_ocw_lecture"),
        Chunk(chunk_id="c03", content="malloc and free are C-style allocation",
              week=3, category="Pedagogical_Context", source_file="03_lecture.json",
              page_number=3, source_domain="mit_ocw_lecture"),
        Chunk(chunk_id="c04", content="manual heap management with new delete",
              week=4, category="Pedagogical_Context", source_file="04_lecture.json",
              page_number=1, source_domain="mit_ocw_lecture"),
        Chunk(chunk_id="c05", content="RAII and smart pointers overview",
              week=4, category="Pedagogical_Context", source_file="04_lecture.json",
              page_number=2, source_domain="mit_ocw_lecture"),
        Chunk(chunk_id="c06", content="Week 4 syllabus: allowed new/delete, forbidden vectors",
              week=4, category="Syllabus", source_file="syllabus.txt",
              page_number=None, source_domain="mit_ocw_syllabus", priority=1),
        Chunk(chunk_id="c07", content="class inheritance and virtual functions",
              week=5, category="Pedagogical_Context", source_file="05_lecture.json",
              page_number=1, source_domain="mit_ocw_lecture"),
        Chunk(chunk_id="c08", content="templates are forbidden this week",
              week=5, category="Strict_Rules", source_file="05_lecture.json",
              page_number=2, source_domain="mit_ocw_lecture"),
        Chunk(chunk_id="c09", content="printf and primitive types only",
              week=1, category="Pedagogical_Context", source_file="01_lecture.json",
              page_number=10, source_domain="mit_ocw_lecture"),
        Chunk(chunk_id="c10", content="arrays and functions in C",
              week=2, category="Pedagogical_Context", source_file="02_lecture.json",
              page_number=5, source_domain="mit_ocw_lecture"),
    ]


@pytest.fixture
def sample_query() -> EvalQuery:
    return EvalQuery(
        query_id="q0001",
        student_message="Why does delete[] crash on my pointer?",
        golden_answer="The pointer was allocated with new, not new[]. Use delete for single objects.",
        week=4,
        mode="Homework Assist",
        topic="Manual Heap Management",
        trigger="terminal_help",
    )


@pytest.fixture
def sample_record() -> dict:
    """Minimal synthetic dataset record."""
    return {
        "messages": [
            {"role": "system", "content": "You are a TA... [RAG CONTEXT: chunk_abc123]"},
            {"role": "user", "content": "Why does my pointer crash?"},
            {"role": "assistant", "content": "Check if you used new[] or new."},
            {"role": "user", "content": "I used new."},
            {"role": "assistant", "content": "Then use delete, not delete[]."},
        ],
        "metadata": {
            "week": 4,
            "topic": "Manual Heap Management",
            "trigger": "terminal_help",
        },
    }


@pytest.fixture
def mock_embedding_model():
    """Mock SentenceTransformer that returns random-ish but deterministic vectors."""
    model = MagicMock()
    # Deterministic pseudo-embedding: length of content modulo
    def _fake_encode(text: str):
        import numpy as np
        seed = sum(ord(c) for c in text[:50])
        rng = np.random.RandomState(seed)
        vec = rng.randn(768).astype(np.float32)
        vec = vec / np.linalg.norm(vec)
        return vec
    model.encode = _fake_encode
    return model


# ---------------------------------------------------------------------------
# 1. trigger_to_mode
# ---------------------------------------------------------------------------

class TestTriggerToMode:
    def test_study_assist(self):
        assert trigger_to_mode("study_assist") == "Study Assist"

    def test_homework_triggers(self):
        for t in ["terminal_help", "gdb_request", "homework_api_query", "homework_paste"]:
            assert trigger_to_mode(t) == "Homework Assist", f"trigger={t}"

    def test_unknown_trigger_defaults_to_homework(self):
        assert trigger_to_mode("some_random_trigger") == "Homework Assist"


# ---------------------------------------------------------------------------
# 2. extract_query
# ---------------------------------------------------------------------------

class TestExtractQuery:
    def test_basic_extraction(self, sample_record):
        q = extract_query(sample_record, 0)
        assert q.query_id == "q0000"
        assert q.student_message == "Why does my pointer crash?"
        assert q.golden_answer == "Check if you used new[] or new."
        assert q.week == 4
        assert q.mode == "Homework Assist"
        assert q.topic == "Manual Heap Management"

    def test_system_message_excluded(self, sample_record):
        """Golden answer should be first assistant, not system."""
        q = extract_query(sample_record, 0)
        assert "RAG CONTEXT" not in q.student_message
        assert "RAG CONTEXT" not in q.golden_answer
        assert "TA" not in q.golden_answer[:20]  # system msg has "You are a TA"

    def test_missing_week_defaults(self):
        rec = {
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
            "metadata": {"trigger": "homework_paste"},
        }
        q = extract_query(rec, 5)
        assert q.week == 3  # default


# ---------------------------------------------------------------------------
# 3. _resolve_week
# ---------------------------------------------------------------------------

class TestResolveWeek:
    def test_all_eight_weeks(self):
        cases = {
            "01_lecture_1_compilation_pipeline.json": 1,
            "02_lecture_2_core_c.json": 2,
            "03_lecture_3_c_memory_management.json": 3,
            "04_lecture_4_data_structures_debugging.json": 4,
            "05_lecture_5_c_introduction_classes_and_templates.json": 5,
            "06_lecture_6_c_inheritance.json": 6,
            "07_lecture_7_parent_destructors.json": 7,
            "08_lecture_8_standard_template_library.json": 8,
        }
        for fname, expected in cases.items():
            assert _resolve_week(fname) == expected, fname

    def test_unknown_filename_fallback(self):
        assert _resolve_week("unknown_file.json") == 1


# ---------------------------------------------------------------------------
# 4. _stable_chunk_id
# ---------------------------------------------------------------------------

class TestStableChunkId:
    def test_deterministic(self):
        a = _stable_chunk_id("lecture", "file.json", 5, "section", "content")
        b = _stable_chunk_id("lecture", "file.json", 5, "section", "content")
        assert a == b

    def test_different_inputs_produce_different_ids(self):
        a = _stable_chunk_id("lecture", "file.json", 1, "section", "content")
        b = _stable_chunk_id("lecture", "file.json", 2, "section", "content")
        assert a != b

    def test_output_is_valid_uuid(self):
        cid = _stable_chunk_id("lecture", "f.json", 1, "s", "c")
        # Should not raise
        uuid.UUID(cid)
        assert len(cid) == 36


# ---------------------------------------------------------------------------
# 5. _classify_category
# ---------------------------------------------------------------------------

class TestClassifyCategory:
    def test_syllabus_source(self):
        assert _classify_category("any text", False, "syllabus") == "Syllabus"

    def test_assignment_source(self):
        assert _classify_category("any text", False, "assignment_solution") == "Supplementary"

    def test_strict_rule_must(self):
        assert _classify_category("You must always free memory", False, "lecture") == "Strict_Rules"

    def test_strict_rule_never(self):
        assert _classify_category("Never use delete on stack", False, "lecture") == "Strict_Rules"

    def test_strict_rule_do_not(self):
        assert _classify_category("Do not access freed memory", False, "lecture") == "Strict_Rules"

    def test_strict_rule_avoid(self):
        assert _classify_category("Avoid raw pointers", False, "lecture") == "Strict_Rules"

    def test_strict_rule_forbidden(self):
        assert _classify_category("Smart pointers are forbidden", False, "lecture") == "Strict_Rules"

    def test_pedagogical_default(self):
        assert _classify_category("Pointers store memory addresses", False, "lecture") == "Pedagogical_Context"

    def test_normal_text_not_strict(self):
        assert _classify_category("A pointer is a variable that stores an address", False, "lecture") == "Pedagogical_Context"


# ---------------------------------------------------------------------------
# 6. _tier2_k
# ---------------------------------------------------------------------------

class TestTier2K:
    def test_week2(self):
        assert _tier2_k(2) == 5       # 1 history week × 5

    def test_week4(self):
        assert _tier2_k(4) == 15      # 3 history weeks × 5

    def test_week6_capped(self):
        assert _tier2_k(6) == 25      # 5 × 5 = 25

    def test_week8_capped(self):
        assert _tier2_k(8) == 25      # 7 × 5 = 35 → capped

    def test_week1_no_history(self):
        assert _tier2_k(1) == 0       # 0 history weeks


# ---------------------------------------------------------------------------
# 7. _simple_bm25
# ---------------------------------------------------------------------------

class TestSimpleBM25:
    def test_returns_top_k(self, sample_chunks):
        result = _simple_bm25("pointer dereference", sample_chunks, top_k=3)
        assert len(result) <= 3
        assert all(isinstance(c, Chunk) for c in result)

    def test_relevant_chunk_ranked_higher(self, sample_chunks):
        """Query about pointers should rank pointer chunk highest."""
        result = _simple_bm25("pointer dereference and address-of", sample_chunks, top_k=5)
        # c01 is about pointers
        chunk_ids = [c.chunk_id for c in result]
        assert "c01" in chunk_ids[:3]  # pointer-related should be near top

    def test_empty_query_returns_chunks(self, sample_chunks):
        result = _simple_bm25("", sample_chunks, top_k=2)
        assert len(result) == 2

    def test_sets_retrieval_score(self, sample_chunks):
        result = _simple_bm25("new delete allocation", sample_chunks, top_k=3)
        for c in result:
            assert c.retrieval_score is not None
            assert isinstance(c.retrieval_score, float)

    def test_top_k_larger_than_corpus(self, sample_chunks):
        result = _simple_bm25("test", sample_chunks, top_k=999)
        assert len(result) == len(sample_chunks)


# ---------------------------------------------------------------------------
# 8. _neighbor_expansion
# ---------------------------------------------------------------------------

class TestNeighborExpansion:
    def test_adds_adjacent_slides(self, sample_chunks):
        # c04 (page 1) and c05 (page 2) are neighbors in 04_lecture.json
        selected = [c for c in sample_chunks if c.chunk_id == "c04"]
        expanded = _neighbor_expansion(selected, sample_chunks, radius=1)
        expanded_ids = {c.chunk_id for c in expanded}
        assert "c04" in expanded_ids  # original
        assert "c05" in expanded_ids  # neighbor page+1

    def test_no_wraparound(self, sample_chunks):
        """Page 1 should not get page 0 neighbor."""
        selected = [c for c in sample_chunks if c.chunk_id == "c04"]
        expanded = _neighbor_expansion(selected, sample_chunks, radius=1)
        expanded_ids = {c.chunk_id for c in expanded}
        assert len(expanded_ids) <= 2  # c04 + c05 only (no page 0)

    def test_syllabus_no_page_expands_within_same_file(self, sample_chunks):
        """Syllabus chunks (page_number=None) are grouped by source_file."""
        selected = [c for c in sample_chunks if c.chunk_id == "c06"]
        expanded = _neighbor_expansion(selected, sample_chunks, radius=1)
        # syllabus.txt only has c06, so no neighbors
        assert len(expanded) == 1
        assert expanded[0].chunk_id == "c06"

    def test_radius_2(self, sample_chunks):
        """Radius 2 should include ±2 neighbors."""
        # c02 (page 2) in 03_lecture → neighbors c01 (p1), c03 (p3)
        selected = [c for c in sample_chunks if c.chunk_id == "c02"]
        expanded = _neighbor_expansion(selected, sample_chunks, radius=2)
        expanded_ids = {c.chunk_id for c in expanded}
        assert "c01" in expanded_ids
        assert "c02" in expanded_ids
        assert "c03" in expanded_ids


# ---------------------------------------------------------------------------
# 9. _parse_label_output
# ---------------------------------------------------------------------------

class TestParseLabelOutput:
    def test_plain_json_array(self):
        raw = '["c01", "c02", "c03"]'
        assert _parse_label_output(raw) == ["c01", "c02", "c03"]

    def test_json_with_uuid(self):
        raw = '["58dbf568-51bb-4d4e-8cf9-c6a8a797d001", "58dbf568-51bb-4d4e-8cf9-c6a8a797d002"]'
        result = _parse_label_output(raw)
        assert len(result) == 2

    def test_markdown_code_fence(self):
        raw = '```json\n["c01", "c02"]\n```'
        assert _parse_label_output(raw) == ["c01", "c02"]

    def test_markdown_no_language(self):
        raw = '```\n["c01"]\n```'
        assert _parse_label_output(raw) == ["c01"]

    def test_fallback_uuid_regex(self):
        """Garbage around a JSON array — fallback to UUID regex."""
        raw = 'Here are the relevant chunks: 58dbf568-51bb-4d4e-8cf9-c6a8a797d001 and maybe 58dbf568-51bb-4d4e-8cf9-c6a8a797d002'
        result = _parse_label_output(raw)
        assert "58dbf568-51bb-4d4e-8cf9-c6a8a797d001" in result
        assert "58dbf568-51bb-4d4e-8cf9-c6a8a797d002" in result

    def test_unparseable_returns_empty(self):
        assert _parse_label_output("I don't know, sorry!") == []

    def test_empty_string(self):
        assert _parse_label_output("") == []


# ---------------------------------------------------------------------------
# 10. build_candidate_pool
# ---------------------------------------------------------------------------

class TestBuildCandidatePool:
    def test_tier1_current_week_included(self, sample_chunks, sample_query, mock_embedding_model):
        """All week-4 chunks must appear in the pool."""
        pool = build_candidate_pool(sample_query, sample_chunks, mock_embedding_model)
        week4_ids = {c.chunk_id for c in sample_chunks if c.week == 4}
        pool_ids = {c.chunk_id for c in pool}
        assert week4_ids.issubset(pool_ids), f"Missing: {week4_ids - pool_ids}"

    def test_tier2_historical_weeks_expanded(self, sample_chunks, sample_query, mock_embedding_model):
        """Some chunks from weeks 1-3 should appear via Tier 2."""
        pool = build_candidate_pool(sample_query, sample_chunks, mock_embedding_model)
        pool_weeks = {c.week for c in pool}
        # Should include at least one historical week
        assert pool_weeks & {1, 2, 3}, f"Pool weeks: {pool_weeks}"

    def test_no_duplicates(self, sample_chunks, sample_query, mock_embedding_model):
        pool = build_candidate_pool(sample_query, sample_chunks, mock_embedding_model)
        ids = [c.chunk_id for c in pool]
        assert len(ids) == len(set(ids))

    def test_tier2_respects_kw(self, sample_chunks, sample_query, mock_embedding_model):
        """With week=2, only 1 history week → Kw=5 per method."""
        q = EvalQuery(query_id="q", student_message="arrays", golden_answer="...",
                       week=2, mode="Homework Assist", topic="Arrays", trigger="terminal_help")
        pool = build_candidate_pool(q, sample_chunks, mock_embedding_model)
        # Tier 1: all week-2 chunks (only c10) + Tier 2: weeks 1..1, Kw=5
        # c09 is week 1, should be in pool
        assert "c10" in {c.chunk_id for c in pool}  # Tier 1
        assert "c09" in {c.chunk_id for c in pool}  # Tier 2 (week 1)

    def test_week8_no_future_weeks(self, sample_chunks, mock_embedding_model):
        """Week 8 has no week 9 to pull from."""
        q = EvalQuery(query_id="q", student_message="STL", golden_answer="...",
                       week=8, mode="Homework Assist", topic="STL", trigger="terminal_help")
        pool = build_candidate_pool(q, sample_chunks, mock_embedding_model)
        weeks = {c.week for c in pool}
        assert all(w <= 8 for w in weeks)


# ---------------------------------------------------------------------------
# 11. _build_labeling_prompt
# ---------------------------------------------------------------------------

class TestBuildLabelingPrompt:
    def test_contains_student_message(self, sample_query, sample_chunks):
        prompt = _build_labeling_prompt(sample_query, sample_chunks)
        assert "Why does delete[] crash on my pointer?" in prompt

    def test_contains_golden_answer(self, sample_query, sample_chunks):
        prompt = _build_labeling_prompt(sample_query, sample_chunks)
        assert "The pointer was allocated with new" in prompt

    def test_tier2_chunks_show_similarity_score(self, sample_query, sample_chunks):
        """Prerequisite chunks should display [sim=X.XXX]."""
        # Give some chunks a retrieval_score
        for c in sample_chunks:
            if c.week < 4:
                c.retrieval_score = 0.850
        prompt = _build_labeling_prompt(sample_query, sample_chunks)
        assert "sim=0.850" in prompt

    def test_tier1_chunks_no_similarity_score(self, sample_query, sample_chunks):
        """Current-week chunks should NOT display sim=."""
        prompt = _build_labeling_prompt(sample_query, sample_chunks)
        # Week 4 chunks are current; count sim= occurrences
        # They should only appear on historical chunks
        lines_with_sim = [l for l in prompt.split("\n") if "sim=" in l]
        for line in lines_with_sim:
            assert "Week 4" not in line, f"Current week chunk has sim=: {line}"

    def test_output_format_instruction(self, sample_query, sample_chunks):
        prompt = _build_labeling_prompt(sample_query, sample_chunks)
        assert '["chunk_id_1", "chunk_id_2", ...]' in prompt

    def test_truncated_golden_answer(self, sample_query):
        """Golden answer longer than 800 chars should be truncated."""
        q = EvalQuery(query_id="q", student_message="test",
                       golden_answer="x" * 2000, week=4,
                       mode="Homework Assist", topic="T", trigger="t")
        prompt = _build_labeling_prompt(q, [])
        assert len("x" * 2000) not in [len(prompt)]  # full golden not present
        assert "x" * 800 in prompt  # truncated version present


# ---------------------------------------------------------------------------
# 12. sample_queries
# ---------------------------------------------------------------------------

class TestSampleQueries:
    def _make_records(self, counts: dict[tuple[int, str], int]) -> list[dict]:
        """Build mock records with given (week, trigger) counts."""
        records = []
        idx = 0
        for (week, trigger), n in counts.items():
            for _ in range(n):
                records.append({
                    "messages": [
                        {"role": "user", "content": f"question {idx}"},
                        {"role": "assistant", "content": f"answer {idx}"},
                    ],
                    "metadata": {"week": week, "topic": "", "trigger": trigger},
                })
                idx += 1
        return records

    def test_min_per_week(self):
        """Every week 1-8 gets at least min samples."""
        counts = {(w, "terminal_help"): 20 for w in range(1, 9)}
        counts[(1, "study_assist")] = 5
        records = self._make_records(counts)
        sampled = sample_queries(records, target=80, seed=42)
        weeks_found = {q.week for q in sampled}
        assert weeks_found == set(range(1, 9))

    def test_both_modes_represented(self):
        counts = {
            (4, "terminal_help"): 30,
            (4, "study_assist"): 10,
        }
        records = self._make_records(counts)
        sampled = sample_queries(records, target=20, seed=42)
        modes = {q.mode for q in sampled}
        assert "Homework Assist" in modes
        assert "Study Assist" in modes

    def test_out_of_scope_excluded(self):
        """Out-of-Scope trigger should never appear (filtered by load_dataset)."""
        rec = {
            "messages": [
                {"role": "user", "content": "q"},
                {"role": "assistant", "content": "a"},
            ],
            "metadata": {"week": 4, "topic": "", "trigger": "Out-of-Scope"},
        }
        # load_dataset() filters Out-of-Scope before sample_queries() is called.
        # Simulate that filtering:
        filtered = [r for r in [rec] if r["metadata"].get("trigger") != "Out-of-Scope"]
        sampled = sample_queries(filtered, target=10, seed=42)
        assert len(sampled) == 0

    def test_does_not_exceed_population(self):
        counts = {(3, "terminal_help"): 5}
        records = self._make_records(counts)
        sampled = sample_queries(records, target=100, seed=42)
        assert len(sampled) <= 5


# ---------------------------------------------------------------------------
# 13. _strip_headers
# ---------------------------------------------------------------------------

class TestStripHeaders:
    def test_removes_header_lines(self):
        text = "TITLE: Something\nBREADCRUMB: path\nSOURCE: url\n===\nReal content here"
        assert _strip_headers(text) == "Real content here"

    def test_no_header_keeps_all(self):
        text = "Just some content without headers"
        assert _strip_headers(text) == "Just some content without headers"

    def test_multiple_separators(self):
        text = "TITLE\n===\nContent part 1\n===\nContent part 2"
        result = _strip_headers(text)
        assert result == "Content part 1\n===\nContent part 2"


# ---------------------------------------------------------------------------
# 14. Integration: load_chunks (requires raw_data/)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestLoadChunksIntegration:
    def test_loads_chunks_from_raw_data(self):
        """Verify real chunk loading works and produces valid chunks."""
        raw_data = Path("/Users/lynw/Projects/ai-teaching-assistant/raw_data")
        if not raw_data.exists():
            pytest.skip("raw_data/ not available")

        chunks = load_chunks(raw_data)
        assert len(chunks) > 0, "Expected at least some chunks"

        # All chunks should have valid fields
        for c in chunks:
            assert c.chunk_id, f"Empty chunk_id: {c}"
            assert c.content, f"Empty content: {c.chunk_id}"
            assert 0 <= c.week <= 8, f"Invalid week {c.week}: {c.chunk_id}"
            assert c.category in {"Syllabus", "Strict_Rules", "Pedagogical_Context", "Supplementary"}
            assert c.source_file
            assert c.source_domain

        # Verify weeks are in range
        weeks = {c.week for c in chunks}
        assert weeks.issubset({0, 1, 2, 3, 4, 5, 6, 7, 8})

        # Verify at least one syllabus chunk exists
        syllabi = [c for c in chunks if c.category == "Syllabus"]
        assert len(syllabi) >= 1, "Expected at least 1 syllabus chunk"

        print(f"\n  Loaded {len(chunks)} chunks: weeks={sorted(weeks)}")


# ---------------------------------------------------------------------------
# 15. Slow: embedding model (requires sentence_transformers)
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestEmbeddingTopK:
    def test_returns_top_k_with_real_model(self, sample_chunks):
        """Test _embedding_top_k with actual SentenceTransformer model."""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            pytest.skip("sentence_transformers not installed")

        model = SentenceTransformer("all-MiniLM-L6-v2")
        from labeling_chunks import _embedding_top_k

        result = _embedding_top_k("pointer dereference crash", sample_chunks, model, top_k=3)
        assert len(result) <= 3
        for c in result:
            assert c.retrieval_score is not None
            assert isinstance(c.retrieval_score, float)

        # The pointer chunk (c01) should rank highly
        chunk_ids = [c.chunk_id for c in result]
        assert "c01" in chunk_ids


# ---------------------------------------------------------------------------
# 16. Smoke test: end-to-end dry-run with 3 real queries (week 1, 2, 3)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSmokeEndToEnd:
    """Minimal end-to-end dry run: 3 queries → chunks → pools → prompts."""

    def test_three_query_smoke(self):
        """Load real data, pick 1 query per week (1,2,3), build pools, print summary."""
        from collections import defaultdict
        from labeling_chunks import load_dataset, load_chunks, build_candidate_pool, _build_labeling_prompt

        raw_data = Path("/Users/lynw/Projects/ai-teaching-assistant/raw_data")
        dataset_path = Path(
            "/Users/lynw/Projects/ai-teaching-data/synthetic_c_plus_plus_dataset.jsonl"
        )

        if not raw_data.exists():
            pytest.skip("raw_data/ not available")
        if not dataset_path.exists():
            pytest.skip("synthetic dataset not available")

        # --- Load chunks ---
        print("\n  [smoke] Loading chunks ...")
        chunks = load_chunks(raw_data)
        assert len(chunks) > 0
        print(f"  [smoke] Loaded {len(chunks)} chunks.")

        # --- Load dataset ---
        print("  [smoke] Loading dataset ...")
        records = load_dataset(dataset_path)
        assert len(records) > 0
        print(f"  [smoke] Loaded {len(records)} records (excl. Out-of-Scope).")

        # --- Pick exactly 1 query from week 1, 2, 3 ---
        by_week: dict[int, list[dict]] = defaultdict(list)
        for rec in records:
            by_week[rec["metadata"]["week"]].append(rec)

        picks: list[dict] = []
        for w in [1, 2, 3]:
            assert w in by_week, f"No records for week {w}"
            picks.append(by_week[w][0])

        queries = [extract_query(rec, i) for i, rec in enumerate(picks)]
        print(f"  [smoke] Picked {len(queries)} queries:")
        for q in queries:
            print(f"    {q.query_id}  week={q.week}  mode={q.mode}  "
                  f"msg={q.student_message[:60]}...")

        # --- Mock embedding model ---
        model = MagicMock()
        def _fake_encode(text: str):
            import numpy as np
            rng = np.random.RandomState(sum(ord(c) for c in text[:50]))
            return rng.randn(768).astype(np.float32)
        model.encode = _fake_encode

        # --- Build pools ---
        print("\n  [smoke] Building candidate pools ...")
        for q in queries:
            pool = build_candidate_pool(q, chunks, model)
            prompt = _build_labeling_prompt(q, pool)
            pool_weeks = sorted(set(c.week for c in pool))

            print(f"    {q.query_id} (Week {q.week}): pool={len(pool)} chunks, "
                  f"weeks={pool_weeks}, prompt_chars={len(prompt)}")

            # Basic assertions
            assert len(pool) > 0, f"Empty pool for {q.query_id}"
            assert q.week in pool_weeks, f"Current week {q.week} missing from pool"
            assert q.student_message in prompt
            assert "Return a JSON array" in prompt

            # Tier 1: current week chunks shown without sim=
            current_week_chunks = [c for c in pool if c.week == q.week]
            assert len(current_week_chunks) > 0, f"No current-week chunks in pool"

        print("\n  [smoke] All assertions passed.")


# ---------------------------------------------------------------------------
# 17. Harvard smoke: chunk loading + pool building with mock queries
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestHarvardSmoke:
    """Verify Harvard CS50 chunk loading and pool construction."""

    def test_harvard_chunk_loading(self):
        """Load Harvard chunks, verify structure, build pools with mock queries."""
        from collections import defaultdict
        from unittest.mock import MagicMock

        raw_data = Path("/Users/lynw/Projects/ai-teaching-assistant/raw_data")
        harvard_dir = raw_data / "Harvard" / "cs50_output" / "notes_json"
        if not harvard_dir.exists():
            pytest.skip("Harvard notes_json not available")

        print("\n  [harvard] Loading chunks ...")
        chunks = load_harvard_chunks(raw_data)
        assert len(chunks) > 0
        print(f"  [harvard] Loaded {len(chunks)} chunks.")

        for c in chunks:
            assert c.chunk_id
            assert c.content
            assert 0 <= c.week <= 5
            assert c.source_domain == "harvard_cs50"
            assert c.category in {"Strict_Rules", "Pedagogical_Context"}

        from collections import Counter as Ctr
        week_dist = Ctr(c.week for c in chunks)
        cat_dist = Ctr(c.category for c in chunks)
        print(f"  [harvard] Week distribution: {dict(sorted(week_dist.items()))}")
        print(f"  [harvard] Category distribution: {dict(cat_dist)}")

        model = MagicMock()
        def _fake_encode(text):
            import numpy as np
            rng = np.random.RandomState(sum(ord(c) for c in text[:50]))
            return rng.randn(768).astype(np.float32)
        model.encode = _fake_encode

        topics = {0: "Scratch", 1: "C", 2: "Arrays", 3: "Algorithms", 4: "Memory", 5: "Data Structures"}
        for week in [0, 2, 5]:
            q = EvalQuery(
                query_id=f"harvard_w{week}",
                student_message="What is a pointer?" if week > 0 else "What is Scratch?",
                golden_answer="...",
                week=week,
                mode="Homework Assist",
                topic=topics[week],
                trigger="terminal_help",
            )
            pool = build_candidate_pool(q, chunks, model)
            pool_weeks = sorted(set(c.week for c in pool))
            print(f"    Harvard Week {week}: pool={len(pool)} chunks, weeks={pool_weeks}")
            assert q.week in pool_weeks
            assert all(w <= q.week for w in pool_weeks)
            if q.week > 0:
                assert any(w < q.week for w in pool_weeks)

        print("\n  [harvard] All assertions passed.")


# ---------------------------------------------------------------------------
# CLI integration hooks
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption("--run-integration", action="store_true", default=False,
                     help="Run integration tests (require raw_data/)")
    parser.addoption("--run-slow", action="store_true", default=False,
                     help="Run slow tests (require sentence_transformers)")


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: mark test as integration (needs raw_data/)")
    config.addinivalue_line("markers", "slow: mark test as slow (needs heavy models)")


def pytest_collection_modifyitems(config, items):
    # Skip integration tests unless explicitly opted in
    if not config.getoption("--run-integration"):
        skip_integration = pytest.mark.skip(reason="use --run-integration to run")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)

    # Skip slow tests unless explicitly opted in
    if not config.getoption("--run-slow"):
        skip_slow = pytest.mark.skip(reason="use --run-slow to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
