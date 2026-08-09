#!/usr/bin/env python3
"""
count_cpp_search_turns.py — how many golden turns trigger cpp guideline search?

Mirrors the search_cpp criterion in llm_eval_retrieval_mit14_claude.py:

    study_assist trigger
      OR  std:: signal          (should_search_cpp)
      OR  C++ AST feature flag   (Has_Iterator / Has_STL_Algorithm / Has_Smart_Pointer)

The functions are imported from the eval module so the criterion stays in sync.
Contextualized follow-up rewrites need LLM calls, so this counter uses each
turn's raw query for both the query and code_raw slots — the std:: check keys
off literal text, which rewriting rarely changes.

By default it counts over the same per-week sample the eval evaluates; pass
--all to count over every session in the golden set.

Usage:
    python count_cpp_search_turns.py --source mit14
    python count_cpp_search_turns.py --source mit14 --all
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

EXPERIMENTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EXPERIMENTS_DIR))

from llm_eval_retrieval_mit14_claude import (
    CPP_FEATURE_FLAGS,
    SOURCE_CONFIG,
    _load_golden_records,
    extract_features_from_text,
    parse_golden_sessions,
    sample_sessions_by_week,
    should_search_cpp,
)


def turn_flags(turn: dict) -> dict[str, bool]:
    """Evaluate the three search_cpp sub-conditions for one turn."""
    query = turn["query"]
    features = turn.get("features") or extract_features_from_text(query)
    is_study_assist = turn.get("trigger") == "study_assist"
    has_std = should_search_cpp(query, code_raw=query)
    has_ast_feature = any(bool(features.get(name)) for name in CPP_FEATURE_FLAGS)
    is_ast_related = has_std or has_ast_feature
    return {
        "study_assist": is_study_assist,
        "std":          has_std,
        "ast_feature":  has_ast_feature,
        "ast_related":  is_ast_related,
        "search_cpp":   is_study_assist or is_ast_related,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["cs50", "mit14"], default="mit14")
    parser.add_argument("--all", action="store_true",
                        help="Count over every session (default: the per-week eval sample).")
    args = parser.parse_args()

    golden_path = SOURCE_CONFIG[args.source]["golden_path"]
    if not golden_path:
        raise ValueError(f"Set RAG_EVAL_GOLDEN_{args.source.upper()}_PATH")

    print(f"Loading golden sessions ({args.source}) from {golden_path} ...")
    sessions = _load_golden_records(golden_path)
    total_sessions = len(sessions)
    selected = sessions if args.all else sample_sessions_by_week(sessions)
    turns = parse_golden_sessions(selected)

    scope = "all" if args.all else "eval sample"
    print(f"  {len(selected)}/{total_sessions} sessions ({scope})  |  {len(turns)} turns")

    flags = [turn_flags(t) for t in turns]
    n = len(flags)

    n_study = sum(f["study_assist"] for f in flags)
    n_std = sum(f["std"] for f in flags)
    n_feat = sum(f["ast_feature"] for f in flags)
    n_ast = sum(f["ast_related"] for f in flags)
    n_cpp = sum(f["search_cpp"] for f in flags)

    # Partition the turns across the two top-level branches
    study_only = sum(1 for f in flags if f["study_assist"] and not f["ast_related"])
    ast_only = sum(1 for f in flags if f["ast_related"] and not f["study_assist"])
    both = sum(1 for f in flags if f["study_assist"] and f["ast_related"])
    neither = sum(1 for f in flags if not f["search_cpp"])

    def pct(x: int) -> str:
        return f"{(x / n * 100 if n else 0):5.1f}%"

    print("\nsearch_cpp criterion: study_assist OR ast_related (std:: OR C++ feature)\n")
    print(f"  turns meeting criterion : {n_cpp:4d} / {n}  ({pct(n_cpp)})")
    print( "  ----------------------------------------------")
    print(f"  study_assist trigger    : {n_study:4d}  ({pct(n_study)})")
    print(f"  ast_related (any)       : {n_ast:4d}  ({pct(n_ast)})")
    print(f"     - std:: signal       : {n_std:4d}  ({pct(n_std)})")
    print(f"     - C++ AST feature    : {n_feat:4d}  ({pct(n_feat)})")
    print( "  ----------------------------------------------")
    print(f"  study_assist only       : {study_only:4d}")
    print(f"  ast_related only        : {ast_only:4d}")
    print(f"  both branches           : {both:4d}")
    print(f"  neither (no cpp search) : {neither:4d}")

    # The branch buckets must partition the turns exactly.
    assert study_only + ast_only + both + neither == n, "branch buckets must sum to n"
    assert study_only + ast_only + both == n_cpp, "cpp buckets must sum to n_cpp"

    triggers = Counter(t["trigger"] for t in turns)
    print(f"\n  Trigger distribution: {dict(triggers.most_common())}")


if __name__ == "__main__":
    main()
