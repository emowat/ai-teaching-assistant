"""
Build the corpus-terms artifact used by the follow-up low-signal detector.

`build_retrieval_query` (rag/query_builder.py) decides whether a follow-up is
"general" (needs conversation context) or "specific" (retrieves on its own). A
word is topical iff it is specialized in general English AND/OR salient in the
course corpus. This script produces the corpus half: the set of tokens that
appear in at least `min_df` course chunks. General-English rarity is supplied at
runtime by `wordfreq`.

Documents = chunks across the course collections (course content only, not the
cpp reference collection). Output: rag/corpus_terms.json
  {"n_docs": N, "min_df": 2, "terms": ["mantissa", "exponent", ...]}

Usage:
  python rag/experiments/build_corpus_terms.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from collections import Counter

from rag.runtime import create_qdrant_client, get_runtime_config

# Course-content collections only (the cpp guideline collection is reference
# material, not the course's own vocabulary baseline).
COURSE_COLLECTIONS = [
    "mit14_course_BAAI_bge_large_en_v1_5",
    "harvard_cs50_BAAI_bge_large_en_v1_5",
]
MIN_DF = 2
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "corpus_terms.json"
_TOKEN = re.compile(r"[a-z][a-z0-9_]+")


def build() -> dict:
    client = create_qdrant_client(get_runtime_config())
    df: Counter[str] = Counter()
    n_docs = 0
    try:
        for collection in COURSE_COLLECTIONS:
            offset = None
            while True:
                points, offset = client.scroll(
                    collection, limit=500, offset=offset,
                    with_payload=True, with_vectors=False,
                )
                for point in points:
                    n_docs += 1
                    content = (point.payload or {}).get("content", "") or ""
                    for token in set(_TOKEN.findall(content.lower())):
                        df[token] += 1
                if offset is None:
                    break
    finally:
        try:
            client.close()
        except Exception:
            pass

    terms = sorted(t for t, c in df.items() if c >= MIN_DF)
    return {"n_docs": n_docs, "min_df": MIN_DF, "terms": terms}


def main() -> None:
    data = build()
    OUTPUT_PATH.write_text(json.dumps(data), encoding="utf-8")
    print(
        f"Wrote {len(data['terms'])} terms (df>={data['min_df']}, "
        f"{data['n_docs']} docs) -> {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()
