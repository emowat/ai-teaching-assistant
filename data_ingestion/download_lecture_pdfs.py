"""
MIT OCW Lecture PDF Downloader
==============================
Discovers and downloads all lecture note PDFs from the MIT OCW 6.S096 course.
Reuses the existing parser to discover PDF links from the index page and
each lecture sub-page, then downloads them.
"""
import argparse
import os
import re
import sys
import time
from urllib.parse import urlparse

import requests

# Reuse the existing parser for discovery
sys.path.insert(0, os.path.dirname(__file__))
from mit_ocw_parser import (
    fetch_page,
    parse_index_page,
    parse_lecture_page,
    BASE_URL,
    DELAY_BETWEEN_REQUESTS,
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
COURSE_INDEX_URL = (
    "https://mitocw.ups.edu.ec/courses/electrical-engineering-and-computer-science/"
    "6-s096-introduction-to-c-and-c-january-iap-2013/lectures-and-assignments/"
)
DEFAULT_OUTDIR = os.path.join(os.path.dirname(__file__), "lecture_notes")
REQUEST_TIMEOUT = 60  # PDFs are larger, give more time


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_pdfs(index_url: str) -> list[dict]:
    """
    Discover all lecture PDF links.

    1. Parse the index page → finds direct PDF links (lectures 7-8)
       and sub-page links (lectures 1-6)
    2. For each sub-page, parse it → find its embedded PDF link

    Returns a list of dicts:
        {"lecture_number": int, "title": str, "url": str, "source_page": str}
    """
    print(f"Discovering PDFs from: {index_url}")
    html = fetch_page(index_url)
    _, lectures = parse_index_page(html, index_url)

    pdfs: list[dict] = []

    for lec in lectures:
        if lec.is_pdf:
            # Direct PDF link (lectures 7-8)
            num = lec.lecture_number or 0
            pdfs.append({
                "lecture_number": num,
                "title": lec.title.replace(" (PDF)", "").replace(" (PDF - 1.4 MB)", ""),
                "url": lec.url,
                "source_page": index_url,
            })
            print(f"  [direct PDF] Lecture {num}: {lec.title}")

        elif lec.is_subpage:
            # Sub-page: fetch and find embedded PDF
            print(f"  [sub-page] Fetching: {lec.title}")
            try:
                sub_html = fetch_page(lec.url)
                parsed = parse_lecture_page(sub_html, lec.url)

                for link in parsed.links:
                    if link["type"] == "pdf":
                        num = lec.lecture_number or _extract_lecture_from_title(link["text"])
                        pdfs.append({
                            "lecture_number": num,
                            "title": link["text"],
                            "url": link["url"],
                            "source_page": lec.url,
                        })
                        print(f"    -> Found PDF: {link['text']}")
                        break  # Usually one PDF per lecture page

                time.sleep(DELAY_BETWEEN_REQUESTS)
            except Exception as e:
                print(f"    ERROR: {e}")

    return pdfs


def _extract_lecture_from_title(title: str) -> int:
    """Fallback: extract lecture number from a PDF link title."""
    m = re.search(r"Lecture\s*(\d+)", title, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 0


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _sanitize_filename(name: str) -> str:
    """Convert a lecture title to a safe filename."""
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = name.strip("_")
    return name[:80] if len(name) > 80 else name


def download_pdfs(pdfs: list[dict], outdir: str) -> list[str]:
    """Download all discovered PDFs to outdir. Returns list of saved paths."""
    os.makedirs(outdir, exist_ok=True)
    saved: list[str] = []

    for i, pdf in enumerate(pdfs, 1):
        num = pdf["lecture_number"]
        title = pdf["title"]
        # Remove noisy suffixes from link text
        clean_title = re.sub(r"\s*\(PDF[^)]*\)", "", title).strip()
        filename = f"{num:02d}_{_sanitize_filename(clean_title)}.pdf"
        filepath = os.path.join(outdir, filename)

        if os.path.exists(filepath):
            print(f"  [{i}/{len(pdfs)}] SKIP (exists): {filename}")
            saved.append(filepath)
            continue

        print(f"  [{i}/{len(pdfs)}] Downloading: {filename}")
        print(f"         from: {pdf['url']}")

        try:
            resp = requests.get(pdf["url"], timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()

            with open(filepath, "wb") as f:
                f.write(resp.content)

            size_kb = len(resp.content) / 1024
            print(f"         OK  ({size_kb:.0f} KB)")
            saved.append(filepath)

        except Exception as e:
            print(f"         FAILED: {e}")

        time.sleep(DELAY_BETWEEN_REQUESTS)

    return saved


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download all lecture note PDFs from the MIT OCW 6.S096 course."
    )
    parser.add_argument(
        "--url", "-u", type=str, default=COURSE_INDEX_URL,
        help="URL of the lectures-and-assignments index page"
    )
    parser.add_argument(
        "--outdir", "-o", type=str, default=DEFAULT_OUTDIR,
        help=f"Output directory for PDFs (default: {DEFAULT_OUTDIR})"
    )
    args = parser.parse_args()

    # 1. Discover
    pdfs = discover_pdfs(args.url)
    print(f"\nDiscovered {len(pdfs)} PDFs.\n")

    if not pdfs:
        print("No PDFs found.")
        return

    # 2. Download
    saved = download_pdfs(pdfs, args.outdir)

    # 3. Summary
    print(f"\nDone. {len(saved)}/{len(pdfs)} PDFs downloaded to {args.outdir}/")
    for p in saved:
        print(f"  {os.path.basename(p)}")


if __name__ == "__main__":
    main()
