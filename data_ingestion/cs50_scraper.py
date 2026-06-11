"""
CS50x Ingestion Scraper (download + parse only)
===============================================
Downloads CS50x Weeks 1-5 lecture NOTES (HTML) and lecture SLIDE PDFs into
raw_data/, and parses the notes into section-level JSON.

Scope: DATA ACQUISITION ONLY. This script does not touch rag/, guardrails,
AST parsing, schemas, Qdrant, or the existing MIT OCW data. It is purely
additive.

Weeks 1-5 are the C-relevant span (1=C, 2=Arrays, 3=Algorithms, 4=Memory,
5=Data Structures). Weeks 6+ (Python/SQL/web) are intentionally out of scope.

CS50x materials are licensed CC BY-NC-SA 4.0 (non-commercial reuse with
attribution + share-alike). See the generated NOTICE.md.

Weeks 0-5 are the C-relevant span (0=Scratch, 1=C, 2=Arrays, 3=Algorithms,
4=Memory, 5=Data Structures). Weeks 6+ (Python/SQL/web) are out of scope.

Outputs (under raw_data/Harvard/):
    raw_data/Harvard/cs50_output/html/notes_<N>.html        raw notes HTML (verbatim)
    raw_data/Harvard/cs50_output/notes_json/notes_<N>.json  parsed section-level JSON
    raw_data/Harvard/cs50_output/manifest.json              per-week ingest manifest
    raw_data/Harvard/cs50_output/NOTICE.md                  attribution + license
    raw_data/Harvard/cs50_lecture_notes/lecture<N>.pdf      lecture slide PDFs
    raw_data/Harvard/cs50_lecture_text/                     created empty (populated
                                                    later by cs50_extract_pdf.py)

Usage:
    # discovery only, prints target URLs, writes nothing:
    python data_ingestion/cs50_scraper.py --dry-run
    # full download + parse:
    python data_ingestion/cs50_scraper.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE = "https://cs50.harvard.edu/x"
WEEKS_URL = BASE + "/weeks/"
WEEKS = [0, 1, 2, 3, 4, 5]

DELAY_BETWEEN_REQUESTS = 0.5     # politeness between network calls
REQUEST_TIMEOUT = 60             # seconds (PDFs can be large)
USER_AGENT = "ai-teaching-assistant-capstone/1.0 (non-commercial academic use)"

LICENSE_NAME = "CC BY-NC-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-nc-sa/4.0/"
CS50_LICENSE_PAGE = "https://cs50.harvard.edu/x/license/"

# Output dirs (anchored to repo's raw_data/Harvard/, sibling of data_ingestion/).
# CS50 (Harvard) data is isolated under raw_data/Harvard/ so it stays separate
# from the flat MIT layout the RAG loader reads.
_HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DATA = os.path.join(_HERE, "..", "raw_data")
HARVARD = os.path.join(RAW_DATA, "Harvard")
CS50_OUTPUT = os.path.join(HARVARD, "cs50_output")
HTML_DIR = os.path.join(CS50_OUTPUT, "html")
NOTES_JSON_DIR = os.path.join(CS50_OUTPUT, "notes_json")
PDF_DIR = os.path.join(HARVARD, "cs50_lecture_notes")
LECTURE_TEXT_DIR = os.path.join(HARVARD, "cs50_lecture_text")
MANIFEST_PATH = os.path.join(CS50_OUTPUT, "manifest.json")
NOTICE_PATH = os.path.join(CS50_OUTPUT, "NOTICE.md")

# CDN fallback for slide PDFs (year/term-dated; only used if no PDF anchor
# is found on the week page). Updated to the current term as needed.
CDN_PDF_FALLBACK = "https://cdn.cs50.net/2025/fall/lectures/{n}/lecture{n}.pdf"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def fetch(url: str, *, binary: bool = False):
    """GET a URL with a polite delay, shared UA, and timeout.

    Returns response.text (or .content if binary). Raises on HTTP error so
    callers can fail loudly per-week.
    """
    time.sleep(DELAY_BETWEEN_REQUESTS)
    resp = requests.get(
        url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}
    )
    resp.raise_for_status()
    if binary:
        return resp.content
    # CS50 serves UTF-8 but declares ISO-8859-1 in headers, which makes
    # requests mis-decode smart quotes/em-dashes into mojibake. Trust the
    # detected encoding instead so text + JSON come out clean.
    resp.encoding = resp.apparent_encoding or resp.encoding
    return resp.text


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_week(n: int) -> dict:
    """Fetch the Week <n> page and extract its title, notes URL, and slides
    PDF URL. Falls back to the CDN PDF pattern only if no PDF anchor exists.

    Returns: {week, week_title, week_url, notes_url, slides_pdf_url,
              slides_from_fallback}
    Raises on any missing piece so the caller can report which week failed.
    """
    week_url = f"{BASE}/weeks/{n}/"
    html = fetch(week_url)
    soup = BeautifulSoup(html, "html.parser")

    # Title: the page <title> is "Week N <Topic> - CS50x <year>". Strip the
    # trailing " - CS50x ..." to get "Week N <Topic>". (The first <h1> on the
    # page is the site banner "This is CS50", not the week title, so we do
    # NOT use it.)
    title = ""
    if soup.title and soup.title.get_text(strip=True):
        title = re.split(r"\s+-\s+CS50", soup.title.get_text(strip=True))[0].strip()
    if not title:
        # Fallback: the week-specific <h1> matching "Week N ...".
        for h1 in soup.find_all("h1"):
            t = h1.get_text(" ", strip=True)
            if re.match(rf"week\s+{n}\b", t, re.IGNORECASE):
                title = t
                break

    # Notes link: an anchor pointing at /notes/<n>/ (relative or absolute).
    notes_url = ""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(rf"/notes/{n}/?($|[?#])", href) or re.search(rf"notes/{n}/?$", href):
            notes_url = urljoin(week_url, href)
            break
    if not notes_url:
        # Canonical fallback — CS50 notes live at a stable path.
        notes_url = f"{BASE}/notes/{n}/"

    # Slides PDF: first anchor whose href ends in .pdf.
    slides_pdf_url = ""
    for a in soup.find_all("a", href=True):
        href = a["href"].split("?")[0]
        if href.lower().endswith(".pdf"):
            slides_pdf_url = urljoin(week_url, a["href"])
            break
    slides_from_fallback = False
    if not slides_pdf_url:
        slides_pdf_url = CDN_PDF_FALLBACK.format(n=n)
        slides_from_fallback = True

    return {
        "week": n,
        "week_title": title or f"Week {n}",
        "week_url": week_url,
        "notes_url": notes_url,
        "slides_pdf_url": slides_pdf_url,
        "slides_from_fallback": slides_from_fallback,
    }


# ---------------------------------------------------------------------------
# Notes HTML -> section JSON
# ---------------------------------------------------------------------------

def _render(node) -> str:
    """Recursively render a content node to text, converting <pre> blocks to
    fenced code blocks (req #12) wherever they are nested.

    CS50 notes nest code deep: <pre> inside div.highlight inside <li> inside
    <ul>. A flat get_text() would lose the fences, so we recurse and emit a
    fenced block for every <pre> we encounter, inline text otherwise.
    """
    name = getattr(node, "name", None)

    # Plain string node.
    if name is None:
        return str(node).strip()

    # A <pre> (code) — fence it. get_text preserves internal newlines/indent.
    if name == "pre":
        code = node.get_text().rstrip("\n")
        return f"```\n{code}\n```"

    # List: one "- " bullet per top-level <li>, each rendered recursively so
    # code blocks inside a bullet survive as fences.
    if name in ("ul", "ol"):
        items = []
        for li in node.find_all("li", recursive=False):
            inner = _render(li).strip()
            if inner:
                # If the bullet contains a fenced block, keep it on its own
                # lines under the bullet rather than mangling the fence.
                if inner.startswith("```") or "\n```" in inner:
                    items.append(f"- {inner}")
                else:
                    items.append(f"- {inner}")
        return "\n".join(items)

    # If this element contains any <pre>, recurse over children so the code
    # is fenced; otherwise take a clean flattened text.
    if node.find("pre"):
        parts = [_render(c) for c in node.children]
        return "\n".join(p for p in (x.strip() for x in parts) if p)

    return node.get_text(" ", strip=True)


def _node_to_text(node) -> str:
    """Render a container node's children to text (fenced code preserved)."""
    parts = [_render(c) for c in node.children]
    return "\n".join(p for p in (x.strip() for x in parts) if p).strip()


def parse_notes_html(html: str, week: int, meta: dict) -> dict:
    """Parse a CS50 notes HTML page into section-level JSON.

    Sections split at h2/h3 heading boundaries. Each section:
        {heading, text, has_code}
    `text` preserves code as fenced blocks; `has_code` flags fenced/inline code.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Find the main notes container; CS50 notes use <main>, fall back to body.
    main = soup.find("main") or soup.body or soup

    headings = main.find_all(["h2", "h3"])
    sections: list[dict] = []

    if not headings:
        # No headings — treat the whole article as one section so we don't
        # silently drop content. Caller checks num_sections for sanity.
        text = _node_to_text(main)
        if text:
            sections.append({
                "heading": meta.get("week_title", f"Week {week}"),
                "text": text,
                "has_code": "```" in text or "`" in text,
            })
        return {
            "week": week,
            "title": meta.get("week_title", f"Week {week}"),
            "url": meta.get("week_url", ""),
            "notes_url": meta.get("notes_url", ""),
            "license": LICENSE_NAME,
            "sections": sections,
        }

    # Walk each heading and collect sibling content until the next heading.
    for h in headings:
        heading_text = h.get_text(" ", strip=True)
        buf: list[str] = []
        for sib in h.next_siblings:
            if getattr(sib, "name", None) in ("h2", "h3"):
                break
            rendered = _render(sib).strip()
            if rendered:
                buf.append(rendered)
        text = "\n\n".join(b for b in buf if b).strip()
        if not heading_text and not text:
            continue
        sections.append({
            "heading": heading_text,
            "text": text,
            "has_code": "```" in text or "`" in text,
        })

    return {
        "week": week,
        "title": meta.get("week_title", f"Week {week}"),
        "url": meta.get("week_url", ""),
        "notes_url": meta.get("notes_url", ""),
        "license": LICENSE_NAME,
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------

def ensure_dirs():
    for d in (CS50_OUTPUT, HTML_DIR, NOTES_JSON_DIR, PDF_DIR, LECTURE_TEXT_DIR):
        os.makedirs(d, exist_ok=True)


def write_notice(weeks_meta: list[dict]):
    lines = [
        "# NOTICE — CS50x Course Materials",
        "",
        "## Attribution",
        "Source: **CS50x — Harvard University** (David J. Malan and CS50 staff).",
        f"Course site: {BASE}/",
        f"License page: {CS50_LICENSE_PAGE}",
        "",
        "## License",
        f"CS50x materials are licensed **{LICENSE_NAME}**",
        f"({LICENSE_URL}).",
        "Reuse and adaptation are permitted for **non-commercial** purposes,",
        "with attribution and share-alike.",
        "",
        "## Changes made",
        "These files were downloaded from CS50x and transformed into",
        "section-level JSON for **non-commercial academic capstone use**.",
        "No CS50 content was altered in substance; the notes HTML was only",
        "reformatted (HTML → section-level JSON, code preserved as fenced",
        "blocks) for retrieval. Slide PDFs are stored unmodified.",
        "",
        "## Sources ingested (Weeks 1-5)",
    ]
    for m in weeks_meta:
        lines.append(f"- Week {m['week']} — {m['week_title']}: {m['notes_url']}")
    lines.append("")
    with open(NOTICE_PATH, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_dry_run():
    print("CS50x scraper — DRY RUN (discovery only, no files written)\n")
    failures = []
    rows = []
    for n in WEEKS:
        try:
            meta = discover_week(n)
            rows.append(meta)
        except Exception as e:  # noqa: BLE001 — report and continue
            print(f"❌ Week {n} discovery failed: {e}")
            failures.append(n)
    print()
    for m in rows:
        fb = "  (PDF via CDN fallback)" if m["slides_from_fallback"] else ""
        print(f"Week {m['week']}: {m['week_title']}")
        print(f"  week_url:       {m['week_url']}")
        print(f"  notes_url:      {m['notes_url']}")
        print(f"  slides_pdf_url: {m['slides_pdf_url']}{fb}")
        print()
    if failures:
        print(f"Discovery failed for weeks: {failures}")
        sys.exit(1)
    print("Dry run complete. No files written.")


def run_full():
    ensure_dirs()
    manifest = []
    failures = []

    for n in WEEKS:
        try:
            print(f"\n=== Week {n} ===")
            meta = discover_week(n)
            if meta["slides_from_fallback"]:
                print(f"  ⚠ no PDF anchor found; using CDN fallback: {meta['slides_pdf_url']}")

            # 1. notes HTML (raw, preserved)
            print(f"  notes: {meta['notes_url']}")
            notes_html = fetch(meta["notes_url"])
            html_path = os.path.join(HTML_DIR, f"notes_{n}.html")
            with open(html_path, "w") as f:
                f.write(notes_html)

            # 2. parse -> section JSON
            parsed = parse_notes_html(notes_html, n, meta)
            num_sections = len(parsed["sections"])
            if num_sections == 0:
                raise ValueError("0 sections parsed from notes HTML (structure changed?)")
            json_path = os.path.join(NOTES_JSON_DIR, f"notes_{n}.json")
            with open(json_path, "w") as f:
                json.dump(parsed, f, indent=2)

            # 3. slides PDF
            print(f"  slides: {meta['slides_pdf_url']}")
            pdf_bytes = fetch(meta["slides_pdf_url"], binary=True)
            pdf_path = os.path.join(PDF_DIR, f"lecture{n}.pdf")
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)

            code_sections = sum(1 for s in parsed["sections"] if s["has_code"])
            print(f"  ✓ {num_sections} sections ({code_sections} with code), "
                  f"PDF {len(pdf_bytes)//1024} KB")

            manifest.append({
                "week": n,
                "week_title": meta["week_title"],
                "week_url": meta["week_url"],
                "notes_url": meta["notes_url"],
                "slides_pdf_url": meta["slides_pdf_url"],
                "local_html_path": os.path.relpath(html_path, RAW_DATA),
                "local_pdf_path": os.path.relpath(pdf_path, RAW_DATA),
                "num_sections": num_sections,
            })
        except Exception as e:  # noqa: BLE001 — fail loudly, keep going
            print(f"❌ Week {n} failed: {e}")
            failures.append(n)

    if manifest:
        with open(MANIFEST_PATH, "w") as f:
            json.dump(manifest, f, indent=2)
        write_notice(manifest)

    print("\n=== Summary: sections extracted per week ===")
    for m in manifest:
        print(f"  Week {m['week']} ({m['week_title']}): {m['num_sections']} sections")
    if failures:
        print(f"\n❌ FAILED weeks: {failures}")
        sys.exit(1)
    print(f"\n✓ Done. Manifest: {MANIFEST_PATH}")


def main():
    parser = argparse.ArgumentParser(description="CS50x Weeks 1-5 ingestion (download + parse).")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="discover and print week/notes/slides URLs only; write nothing",
    )
    args = parser.parse_args()
    if args.dry_run:
        run_dry_run()
    else:
        run_full()


if __name__ == "__main__":
    main()
