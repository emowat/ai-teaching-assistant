"""Data-loading tests for the input CodeBERT guardrail (no ML deps required).

Run from ai-teaching-assistant/:
    pytest input_guardrails/tests/ -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from input_guardrails.models.data_utils import (
    apply_splits,
    assert_no_context_leakage,
    context_ids,
    format_example,
    load_jsonl,
    load_splits,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "classifier_data"
CANDIDATES = DATA_DIR / "input_classifier_dataset_v1_candidates.jsonl"
HARD_GOLD = DATA_DIR / "input_hard_gold_v1.jsonl"
SPLITS = DATA_DIR / "splits_input_v1.json"


@pytest.fixture(scope="module")
def candidates():
    return load_jsonl(CANDIDATES)


@pytest.fixture(scope="module")
def hard_gold():
    return load_jsonl(HARD_GOLD)


@pytest.fixture(scope="module")
def splits():
    return load_splits(SPLITS)


def test_1_candidates_load(candidates):
    assert len(candidates) > 0
    assert all("user_query" in r and "label" in r for r in candidates)


def test_2_hard_gold_loads(hard_gold):
    assert len(hard_gold) > 0
    assert all("context_id" in r for r in hard_gold)


def test_3_splits_load(splits):
    assert len(splits) > 0
    assert set(splits.values()) <= {"train", "val", "test"}


def test_4_split_by_context_no_leakage(candidates, splits):
    buckets, unassigned = apply_splits(candidates, splits)
    assert not unassigned, f"{len(unassigned)} candidate rows had no split entry"
    # raises if any context appears in >1 split
    assert_no_context_leakage(buckets)
    # every split non-empty
    for name in ("train", "val", "test"):
        assert buckets[name], f"empty split: {name}"


def test_5_formatted_input_has_all_sections(candidates):
    text = format_example(candidates[0])
    for tag in ("[USER_QUERY]", "[STUDENT_CODE]", "[COURSE_TOPIC]", "[ASSIGNMENT_CONTEXT]"):
        assert tag in text, f"missing section tag {tag}"


def test_6_labels_are_binary(candidates, hard_gold):
    for r in candidates + hard_gold:
        assert int(r["label"]) in (0, 1), f"bad label in {r.get('id')}"


def test_7_hard_gold_contexts_disjoint_from_candidates(candidates, hard_gold):
    overlap = context_ids(candidates) & context_ids(hard_gold)
    assert not overlap, f"hard gold leaks into candidate contexts: {overlap}"


def test_8_should_call_llm_consistent_with_label(candidates, hard_gold):
    # label 1 -> should_call_llm False ; label 0 -> True
    for r in candidates + hard_gold:
        if "should_call_llm" in r:
            assert r["should_call_llm"] == (int(r["label"]) == 0)
