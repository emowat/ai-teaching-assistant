"""
CS50x Lecture Transcript Downloader + Parser
=============================================
Downloads CS50x Weeks 1-5 lecture transcripts (plain .txt) from the CDN and
breaks the single-continuous-line verbatim text into paragraph-level JSON.

Source: https://cdn.cs50.net/2025/fall/lectures/{n}/lang/en/lecture{n}.txt
These are spoken-word transcripts of the live lectures — single long line,
no newlines, ~120K-155K chars each.

Scope: DATA ACQUISITION ONLY. Follows the same conventions as cs50_scraper.py
(reuses its output directories under raw_data/Harvard/).

Outputs (under raw_data/Harvard/cs50_transcripts/):
    lecture{N}_raw.txt   — verbatim downloaded text (single line)
    lecture{N}.txt       — cleaned text (sentence-broken into paragraphs)
    lecture{N}.json      — paragraph-level JSON for downstream RAG ingestion
    manifest.json         — per-week ingest manifest

Usage:
    # dry-run: print URLs only
    python data_ingestion/cs50_download_transcripts.py --dry-run

    # full download + parse
    python data_ingestion/cs50_download_transcripts.py

    # re-parse already-downloaded raw files (skip network)
    python data_ingestion/cs50_download_transcripts.py --parse-only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

WEEKS = [1, 2, 3, 4, 5]
CDN_TRANSCRIPT_URL = "https://cdn.cs50.net/2025/fall/lectures/{n}/lang/en/lecture{n}.txt"

# Week titles (mirrors cs50_scraper.py naming)
WEEK_TITLES: dict[int, str] = {
    1: "Week 1 C",
    2: "Week 2 Arrays",
    3: "Week 3 Algorithms",
    4: "Week 4 Memory",
    5: "Week 5 Data Structures",
}

DELAY_BETWEEN_REQUESTS = 0.5
REQUEST_TIMEOUT = 60
USER_AGENT = "ai-teaching-assistant-capstone/1.0 (non-commercial academic use)"

# Output dirs — aligned with cs50_scraper.py layout
_HERE = Path(__file__).resolve().parent
RAW_DATA = _HERE.parent / "raw_data"
HARVARD = RAW_DATA / "Harvard"
TRANSCRIPTS_DIR = HARVARD / "cs50_transcripts"
MANIFEST_PATH = TRANSCRIPTS_DIR / "manifest.json"

# Sentence-boundary pattern for paragraph splitting.
# Splits on . ! ? followed by space+capital letter (or end of string).
# Handles common abbreviations (Mr. Dr. etc.) to avoid false splits.
_SENTENCE_SPLIT = re.compile(
    r"(?<=[.!?])\s+(?=[A-Z])"
)

# Minimum characters per paragraph — shorter segments get merged with the next.
MIN_PARAGRAPH_CHARS = 80

# Maximum characters per paragraph — longer paragraphs get split further.
MAX_PARAGRAPH_CHARS = 1200


# ---------------------------------------------------------------------------
# HTTP helpers (mirrors cs50_scraper.py)
# ---------------------------------------------------------------------------

def fetch_transcript(week: int) -> str:
    """Download a single week's transcript, return raw text."""
    url = CDN_TRANSCRIPT_URL.format(n=week)
    time.sleep(DELAY_BETWEEN_REQUESTS)
    resp = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


# ---------------------------------------------------------------------------
# Parsing: single long line → paragraph-level text
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """Minimal cleanup: normalize whitespace, strip control chars."""
    # Replace any remaining control characters except newline
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
    # Collapse multiple spaces
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse 3+ newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_sentences(text: str) -> list[str]:
    """Split a long text into sentences using punctuation boundaries."""
    # First pass: split on sentence-ending punctuation followed by capital letter
    raw_sentences = _SENTENCE_SPLIT.split(text)

    # Second pass: handle edge cases — merge back abbreviations that got split.
    # Common CS lecture patterns that should not be sentence breaks.
    abbreviations = {
        "e.g", "i.e", "vs", "Mr", "Mrs", "Ms", "Dr", "Prof",
        "etc", "al",  # "et al."
    }
    merged: list[str] = []
    for s in raw_sentences:
        s = s.strip()
        if not s:
            continue
        if merged:
            # Check if previous sentence ends with an abbreviation
            prev = merged[-1]
            prev_last_word = prev.rstrip(".").split()[-1].rstrip(".") if prev.split() else ""
            if prev_last_word.lower() in abbreviations:
                merged[-1] = prev + " " + s
                continue
        merged.append(s)

    return merged


def _build_paragraphs(sentences: list[str]) -> list[str]:
    """Merge sentences into reasonably-sized paragraphs.

    Rules:
    - Start a new paragraph at natural topic shifts (e.g., "So ", "Now ",
      "All right", "Any questions", "Let's").
    - Merge short segments until MIN_PARAGRAPH_CHARS is reached.
    - Split long paragraphs if they exceed MAX_PARAGRAPH_CHARS.
    """
    # First pass: group into candidate paragraphs at topic-shift signals
    topic_shift_pattern = re.compile(
        r"^(So\b|Now\b|All right|Any questions|Let'?s\b|Okay|Well\b|Anyway|"
        r"Moving on|Meanwhile|In fact|But\b|And\b|However)",
        re.IGNORECASE,
    )

    candidates: list[list[str]] = [[]]
    for s in sentences:
        if topic_shift_pattern.match(s) and candidates[-1]:
            # Start a new paragraph
            candidates.append([s])
        else:
            candidates[-1].append(s)

    # Merge and enforce size constraints
    paragraphs: list[str] = []
    current: list[str] = []

    for group in candidates:
        group_text = " ".join(group).strip()
        if not group_text:
            continue

        if current:
            combined = current + group
            combined_text = " ".join(combined).strip()
            if len(combined_text) < MIN_PARAGRAPH_CHARS:
                current.extend(group)
                continue
            else:
                paragraphs.append(" ".join(current).strip())
                current = group
        else:
            current = group

    # Flush remaining
    if current:
        paragraphs.append(" ".join(current).strip())

    # Split long paragraphs
    result: list[str] = []
    for p in paragraphs:
        if len(p) <= MAX_PARAGRAPH_CHARS:
            result.append(p)
        else:
            # Split at sentence boundary closest to MAX_PARAGRAPH_CHARS
            sub_sentences = _split_sentences(p)
            chunk: list[str] = []
            chunk_len = 0
            for s in sub_sentences:
                if chunk and chunk_len + len(s) > MAX_PARAGRAPH_CHARS:
                    result.append(" ".join(chunk).strip())
                    chunk = [s]
                    chunk_len = len(s)
                else:
                    chunk.append(s)
                    chunk_len += len(s)
            if chunk:
                result.append(" ".join(chunk).strip())

    return result


def parse_transcript(raw_text: str, week: int) -> dict:
    """Parse a raw transcript into paragraph-level structured JSON.

    Args:
        raw_text: The verbatim transcript text (single long line).
        week: Week number (1-5).

    Returns:
        dict with keys: week, title, source_url, paragraphs (list of
        {index, text, char_count}), total_paragraphs, total_chars.
    """
    # Normalize: the raw text may have embedded newlines — flatten to one line
    flat = raw_text.replace("\n", " ").replace("\r", " ")
    flat = _clean_text(flat)

    # Split into sentences, then group into paragraphs
    sentences = _split_sentences(flat)
    paragraphs = _build_paragraphs(sentences)

    # Build structured output
    para_list: list[dict] = []
    for i, p in enumerate(paragraphs):
        para_list.append({
            "index": i,
            "text": p,
            "char_count": len(p),
        })

    return {
        "week": week,
        "title": WEEK_TITLES.get(week, f"Week {week}"),
        "source_url": CDN_TRANSCRIPT_URL.format(n=week),
        "paragraphs": para_list,
        "total_paragraphs": len(para_list),
        "total_chars": sum(p["char_count"] for p in para_list),
    }


def build_flat_text(parsed: dict) -> str:
    """Convert parsed JSON back to clean human-readable flat text."""
    parts: list[str] = [
        f"Week {parsed['week']}: {parsed['title']}",
        f"Source: {parsed['source_url']}",
        f"Paragraphs: {parsed['total_paragraphs']}",
        "=" * 70,
        "",
    ]
    for p in parsed["paragraphs"]:
        parts.append(p["text"])
        parts.append("")  # blank line between paragraphs
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_dry_run():
    """Print target URLs without downloading anything."""
    print("CS50x transcript downloader — DRY RUN (URLs only, no files written)\n")
    for n in WEEKS:
        url = CDN_TRANSCRIPT_URL.format(n=n)
        print(f"Week {n} ({WEEK_TITLES.get(n, '')}):")
        print(f"  {url}")
        print()


def run_download():
    """Download all transcripts from CDN and parse them."""
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
    manifest: list[dict] = []

    for week in WEEKS:
        print(f"\n=== Week {week} ===")
        url = CDN_TRANSCRIPT_URL.format(n=week)

        try:
            # 1. Download raw transcript
            print(f"  Downloading: {url}")
            raw_text = fetch_transcript(week)
            raw_chars = len(raw_text)
            print(f"  Downloaded {raw_chars} chars.")

            # 2. Save raw (verbatim)
            raw_path = TRANSCRIPTS_DIR / f"lecture{week}_raw.txt"
            raw_path.write_text(raw_text, encoding="utf-8")
            print(f"  Raw → {raw_path}")

            # 3. Parse → paragraph JSON
            parsed = parse_transcript(raw_text, week)
            para_count = parsed["total_paragraphs"]
            print(f"  Parsed → {para_count} paragraphs ({parsed['total_chars']} chars)")

            json_path = TRANSCRIPTS_DIR / f"lecture{week}.json"
            json_path.write_text(
                json.dumps(parsed, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"  JSON → {json_path}")

            # 4. Clean flat text
            txt_path = TRANSCRIPTS_DIR / f"lecture{week}.txt"
            flat_text = build_flat_text(parsed)
            txt_path.write_text(flat_text, encoding="utf-8")
            print(f"  TXT → {txt_path}")

            manifest.append({
                "week": week,
                "title": parsed["title"],
                "source_url": url,
                "raw_chars": raw_chars,
                "paragraphs": para_count,
                "total_chars": parsed["total_chars"],
                "raw_file": str(raw_path.relative_to(RAW_DATA)),
                "txt_file": str(txt_path.relative_to(RAW_DATA)),
                "json_file": str(json_path.relative_to(RAW_DATA)),
            })

        except Exception as e:
            print(f"  ❌ Week {week} failed: {e}")
            continue

    # Write manifest
    if manifest:
        MANIFEST_PATH.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n✓ Manifest → {MANIFEST_PATH}")

    # Summary
    print(f"\n{'='*60}")
    print("Summary:")
    for m in manifest:
        print(f"  Week {m['week']} ({m['title']}): "
              f"{m['paragraphs']} paragraphs, {m['total_chars']:,} chars")
    print(f"\n✓ Done. {len(manifest)}/{len(WEEKS)} weeks ingested.")
    print(f"  Output dir: {TRANSCRIPTS_DIR}")


def run_parse_only():
    """Re-parse already-downloaded raw files (no network)."""
    if not TRANSCRIPTS_DIR.exists():
        print(f"ERROR: {TRANSCRIPTS_DIR} does not exist. Run download first.")
        sys.exit(1)

    manifest: list[dict] = []

    for week in WEEKS:
        raw_path = TRANSCRIPTS_DIR / f"lecture{week}_raw.txt"
        if not raw_path.exists():
            print(f"Week {week}: raw file not found, skipping.")
            continue

        print(f"\n=== Week {week} (re-parse) ===")
        raw_text = raw_path.read_text(encoding="utf-8")
        print(f"  Loaded {len(raw_text)} chars from {raw_path.name}")

        parsed = parse_transcript(raw_text, week)
        para_count = parsed["total_paragraphs"]
        print(f"  Parsed → {para_count} paragraphs ({parsed['total_chars']} chars)")

        json_path = TRANSCRIPTS_DIR / f"lecture{week}.json"
        json_path.write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        txt_path = TRANSCRIPTS_DIR / f"lecture{week}.txt"
        flat_text = build_flat_text(parsed)
        txt_path.write_text(flat_text, encoding="utf-8")

        print(f"  JSON → {json_path}")
        print(f"  TXT → {txt_path}")

        manifest.append({
            "week": week,
            "title": parsed["title"],
            "source_url": CDN_TRANSCRIPT_URL.format(n=week),
            "raw_chars": len(raw_text),
            "paragraphs": para_count,
            "total_chars": parsed["total_chars"],
            "raw_file": str(raw_path.relative_to(RAW_DATA)),
            "txt_file": str(txt_path.relative_to(RAW_DATA)),
            "json_file": str(json_path.relative_to(RAW_DATA)),
        })

    if manifest:
        MANIFEST_PATH.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n✓ Manifest → {MANIFEST_PATH}")

    print(f"\n✓ Re-parse complete. {len(manifest)} weeks processed.")


def main():
    parser = argparse.ArgumentParser(
        description="CS50x Weeks 1-5 lecture transcript downloader + parser."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print target URLs only; write nothing.",
    )
    parser.add_argument(
        "--parse-only", action="store_true",
        help="Re-parse already-downloaded raw files; skip network.",
    )
    args = parser.parse_args()

    if args.dry_run:
        run_dry_run()
    elif args.parse_only:
        run_parse_only()
    else:
        run_download()


if __name__ == "__main__":
    main()
