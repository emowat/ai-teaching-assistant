"""
Phase 2A: Extract CS50 slide PDFs into page-level JSON.

REUSES the existing MIT extraction logic from extract_pdf_text.py
(extract_pdf, slides_to_flat_text, and its _clean_text/_has_code/
_is_section_header heuristics) — no extraction logic is duplicated here.
This runner only repoints input/output at the CS50 (Harvard) folders.

Scope: PDF -> JSON/TXT only. Does NOT build RAG chunks, touch Qdrant,
rag/loader.py, schemas, guardrails, AST, thresholds, or any MIT data.

Input:
    raw_data/Harvard/cs50_lecture_notes/lecture{1..5}.pdf
Output (matches MIT JSON structure [{page, section, text, has_code}]):
    raw_data/Harvard/cs50_lecture_text/lecture{1..5}.json
    raw_data/Harvard/cs50_lecture_text/lecture{1..5}.txt

Run from repo root:
    python data_ingestion/cs50_extract_pdf.py
"""

from __future__ import annotations

import json
import os
import sys

# Reuse the existing MIT extractor's functions verbatim.
sys.path.insert(0, os.path.dirname(__file__))
from extract_pdf_text import extract_pdf, slides_to_flat_text

_HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DATA = os.path.join(_HERE, "..", "raw_data")
PDF_DIR = os.path.join(RAW_DATA, "Harvard", "cs50_lecture_notes")
OUT_DIR = os.path.join(RAW_DATA, "Harvard", "cs50_lecture_text")

LECTURES = [1, 2, 3, 4, 5]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    summary = []      # (lecture, num_pages, code_pages)
    total_pages = 0

    for n in LECTURES:
        pdf_path = os.path.join(PDF_DIR, f"lecture{n}.pdf")
        base = f"lecture{n}"

        # Fail loudly: missing PDF.
        if not os.path.isfile(pdf_path):
            print(f"❌ FAILED: PDF not found: {pdf_path}")
            sys.exit(1)

        print(f"  {base}.pdf: ", end="", flush=True)
        slides = extract_pdf(pdf_path)

        # Fail loudly: zero pages extracted.
        if not slides:
            print("0 pages")
            print(f"❌ FAILED: extraction produced 0 pages for {pdf_path}")
            sys.exit(1)

        json_path = os.path.join(OUT_DIR, f"{base}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(slides, f, ensure_ascii=False, indent=2)

        txt_path = os.path.join(OUT_DIR, f"{base}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(slides_to_flat_text(slides))

        code_pages = sum(1 for s in slides if s["has_code"])
        total_pages += len(slides)
        summary.append((n, len(slides), code_pages))
        print(f"{len(slides)} pages ({code_pages} with code) -> {json_path}")

    # ---- Required reporting ----
    print("\n=== Extraction summary ===")
    for n, pages, code_pages in summary:
        print(f"  lecture{n}: {pages} pages, {code_pages} with has_code=true")
    print(f"  TOTAL: {total_pages} pages across {len(summary)} lectures")

    # Sample: lecture4 page 1, or first non-empty page if page 1 is sparse.
    l4_path = os.path.join(OUT_DIR, "lecture4.json")
    with open(l4_path, encoding="utf-8") as f:
        l4 = json.load(f)
    sample = next((s for s in l4 if s["text"].strip()), l4[0])
    print("\n=== Sample: lecture4.json (first non-empty page) ===")
    print(f"  page: {sample['page']} | section: {sample['section']!r} | "
          f"has_code: {sample['has_code']}")
    print("  text:")
    print("    " + sample["text"][:500].replace("\n", "\n    "))


if __name__ == "__main__":
    main()
