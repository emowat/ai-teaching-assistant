"""
Download assignment solution PDFs from MIT OCW lecture sub-pages.

Scans each lecture sub-page for PDF links containing "sol" (solution),
then downloads them. Only assignments 1 and 3 have published solutions.
"""
import os
import re
import sys
import time

import requests

# Reuse existing parser
sys.path.insert(0, os.path.dirname(__file__))
from mit_ocw_parser import (
    fetch_page,
    parse_index_page,
    parse_lecture_page,
    DELAY_BETWEEN_REQUESTS,
)

COURSE_INDEX_URL = (
    "https://mitocw.ups.edu.ec/courses/electrical-engineering-and-computer-science/"
    "6-s096-introduction-to-c-and-c-january-iap-2013/lectures-and-assignments/"
)
OUT_DIR = os.path.join(os.path.dirname(__file__), "assignment_solutions")
REQUEST_TIMEOUT = 60


def discover_solution_pdfs(index_url: str) -> list[dict]:
    """Scan all lecture sub-pages for solution PDF links."""
    print("Scanning lecture pages for solution PDFs...\n")
    html = fetch_page(index_url)
    _, lectures = parse_index_page(html, index_url)

    solutions: list[dict] = []

    for lec in lectures:
        if not lec.is_subpage:
            continue

        num = lec.lecture_number or 0
        print(f"  Lecture {num}: {lec.title[:60]}...", end=" ", flush=True)

        try:
            sub_html = fetch_page(lec.url)
            parsed = parse_lecture_page(sub_html, lec.url)

            found = False
            for link in parsed.links:
                if link["type"] == "pdf" and "sol" in link["url"].lower():
                    solutions.append({
                        "lecture_number": num,
                        "title": link["text"],
                        "url": link["url"],
                    })
                    print(f"FOUND: {link['text']}")
                    found = True
                    break

            if not found:
                # Check if solutions explicitly unavailable
                if "not available" in parsed.text.lower():
                    print("not available")
                else:
                    print("none found")

            time.sleep(DELAY_BETWEEN_REQUESTS)

        except Exception as e:
            print(f"ERROR: {e}")

    return solutions


def download_solutions(solutions: list[dict], outdir: str) -> list[str]:
    """Download solution PDFs."""
    os.makedirs(outdir, exist_ok=True)
    saved: list[str] = []

    for i, sol in enumerate(solutions, 1):
        num = sol["lecture_number"]
        filename = f"assignment{num}_solution.pdf"
        filepath = os.path.join(outdir, filename)

        if os.path.exists(filepath):
            print(f"  SKIP (exists): {filename}")
            saved.append(filepath)
            continue

        print(f"  Downloading: {filename}")
        print(f"    from: {sol['url']}")

        try:
            resp = requests.get(sol["url"], timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(resp.content)
            size_kb = len(resp.content) / 1024
            print(f"    OK ({size_kb:.0f} KB)")
            saved.append(filepath)
        except Exception as e:
            print(f"    FAILED: {e}")

        time.sleep(DELAY_BETWEEN_REQUESTS)

    return saved


def main():
    solutions = discover_solution_pdfs(COURSE_INDEX_URL)
    print(f"\nFound {len(solutions)} solution PDFs.\n")

    if not solutions:
        print("No solutions found.")
        return

    saved = download_solutions(solutions, OUT_DIR)
    print(f"\nDone. {len(saved)}/{len(solutions)} downloaded to {OUT_DIR}/")
    for p in saved:
        print(f"  {os.path.basename(p)}")


if __name__ == "__main__":
    main()
