"""
C++ Reference (cppreference.com) Book Parser
============================================
Parses the cppreference HTML book from PeterFeicht/cppreference-doc
into structured JSON for downstream RAG ingestion.

Input:
  A tarball (tar.xz) of the cppreference HTML book, organized as:
    reference/en/cpp/
      container.html          — overview page
      container/vector.html   — API detail page
      container/vector/begin.html — member function page
      algorithm.html
      algorithm/find.html
      ...

Output:
  JSON: one record per non-overview HTML page, each with:
    - name:       e.g. "std::vector", "std::find"
    - path:       e.g. "cpp/container/vector"
    - category:   e.g. "container", "algorithm"
    - header:     e.g. "<vector>"
    - declarations: list of function/class signatures
    - description: introductory text
    - sections:   dict of {h3_heading: text} (Parameters, Return value, etc.)
    - example:    code example text
    - see_also:   list of related items
    - members:    list of member function entries (for class pages)
    - content:    full cleaned plain text (for embeddings)

Usage:
  # Download + parse, write JSON to default output dir
  python parse_cppreference.py

  # Specify a local tarball or extract directory
  python parse_cppreference.py --book ./html-book-20250209.tar.xz

  # If already extracted:
  python parse_cppreference.py --dir ./reference/en/cpp

  # Specify output directory
  python parse_cppreference.py --outdir ./cppref_output

  # Only parse specific categories
  python parse_cppreference.py --categories container,algorithm
"""

import argparse
import json
import os
import re
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BOOK_URL = (
    "https://github.com/PeterFeicht/cppreference-doc/releases/download/"
    "v20250209/html-book-20250209.tar.xz"
)
BOOK_FILENAME = "html-book-20250209.tar.xz"
BOOK_STRIP_PREFIX = "reference/en/cpp/"
REQUEST_TIMEOUT = 300
DEFAULT_OUTDIR = os.path.join(os.path.dirname(__file__), "cppreference_output")

# Tags to remove before text extraction
REMOVE_TAGS = ["script", "style", "nav", "footer", "header", "noscript"]

# All top-level categories in the cppreference book
# (directories + some top-level files under reference/en/cpp/)
ALL_CATEGORIES = [
    "algorithm", "atomic", "chrono", "comment", "compiler_support",
    "concepts", "container", "coroutine", "debugging", "error",
    "experimental", "feature_test", "filesystem", "freestanding",
    "header", "io", "iterator", "keywork", "language", "links",
    "locale", "memory", "meta", "named_req", "numeric",
    "preprocessor", "ranges", "regex", "string", "symbol_index",
    "text", "thread", "types", "utility",
]

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class MemberEntry:
    """A member function / type / non-member function entry."""
    name: str = ""
    url: str = ""         # relative href
    description: str = ""


@dataclass
class CppRefEntry:
    """Represents one parsed API reference page."""
    name: str = ""                          # e.g. "std::vector"
    path: str = ""                          # e.g. "cpp/container/vector"
    category: str = ""                      # e.g. "container"
    header: str = ""                        # e.g. "<vector>"
    declarations: list[str] = field(default_factory=list)
    description: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    example: str = ""
    see_also: list[str] = field(default_factory=list)
    members: list[MemberEntry] = field(default_factory=list)
    content: str = ""                       # full cleaned text


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _fetch_book(url: str, dest: str) -> str:
    """Download the book tarball. Returns path to downloaded file."""
    print(f"Downloading book from {url} ...")
    resp = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded * 100 // total
                print(f"\r  {downloaded >> 20} / {total >> 20} MB ({pct}%)", end="", flush=True)
    print()
    return dest


def _clean_text(text: str) -> str:
    """Collapse whitespace and strip."""
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _remove_unwanted(soup: BeautifulSoup) -> None:
    """Remove script, style, and other noise tags in place."""
    for tag_name in REMOVE_TAGS:
        for el in soup.find_all(tag_name):
            el.decompose()

    # Remove the Google Analytics script
    for el in soup.find_all("script", src=True):
        if "googletagmanager" in (el.get("src") or ""):
            el.decompose()

    # Remove sidebar / banner
    for cls in ["sidebar", "banner"]:
        for el in soup.find_all("div", class_=cls):
            el.decompose()


def _page_title(soup: BeautifulSoup) -> str:
    """Extract the page title from <h1 id='firstHeading'>."""
    h1 = soup.find("h1", id="firstHeading")
    if h1:
        # Use separator="" to avoid GeSHi span artifacts like "std:: vector"
        raw = h1.get_text(separator="", strip=True)
        raw = re.sub(r"[ \t]+", " ", raw)
        return raw.strip()
    # Fallback: <title> tag
    title_tag = soup.find("title")
    if title_tag:
        t = title_tag.get_text(strip=True)
        if " - cppreference.com" in t:
            t = t.split(" - cppreference.com")[0]
        return t.strip()
    return ""


def _page_path(filepath: str) -> str:
    """
    Convert a file path like 'reference/en/cpp/container/vector.html'
    to 'cpp/container/vector'.
    """
    parts = Path(filepath).parts
    # Find 'cpp' in parts and join everything after it
    try:
        idx = parts.index("cpp")
        rel = "/".join(parts[idx:])
    except ValueError:
        rel = "/".join(parts)
    if rel.endswith(".html"):
        rel = rel[:-5]
    return rel


def _page_category(filepath: str) -> str:
    """
    Extract the top-level category from the path.
    'cpp/container/vector' -> 'container'
    'cpp/algorithm/find' -> 'algorithm'
    """
    path = _page_path(filepath)
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] == "cpp":
        return parts[1]
    return ""


# ---------------------------------------------------------------------------
# Page parsers
# ---------------------------------------------------------------------------


def _parse_t_dcl_begin(content_div: Tag) -> tuple[str, list[str]]:
    """
    Parse the t-dcl-begin table.
    Returns (header, [declarations]).
    Header is the first row ("Defined in header <vector>").
    Declarations are the actual signatures.
    """
    dcl_table = content_div.find("table", class_="t-dcl-begin")
    if not dcl_table:
        return "", []

    header = ""
    declarations: list[str] = []
    for row in dcl_table.find_all("tr"):
        tds = row.find_all("td")
        if not tds:
            continue

        # First td usually holds the main declaration text;
        # subsequent tds hold version markers like "(1)", "(since C++20)" etc.
        # Preserve natural whitespace, then normalize via _clean_text
        # (which handles \xa0 -> space, collapsing multi-spaces)
        main_text = _clean_text(tds[0].get_text(separator="", strip=False))
        # Re-collapse newlines within declarations (declarations are single-line)
        main_text = re.sub(r"\n+", " ", main_text)

        # Collect suffix markers from remaining tds
        suffixes: list[str] = []
        for td in tds[1:]:
            suffix = td.get_text(strip=True)
            if suffix:
                suffixes.append(suffix)

        # Assemble: "declaration (1) (since C++20)"
        if not main_text:
            continue

        if "Defined in header" in main_text:
            m = re.search(r"Defined in header\s*(<[^>]+>)", main_text)
            header = m.group(1) if m else main_text
        else:
            full_decl = main_text
            if suffixes:
                full_decl += " " + " ".join(suffixes)
            declarations.append(_clean_text(full_decl))

    return header, declarations


def _parse_sections(content_div: Tag) -> tuple[dict[str, str], str, str]:
    """
    Parse h3-headed sections within the content.
    Returns (sections, example, description).

    description = text before the first h3.
    sections = {h3_heading_name: text_before_next_h3}.
    example = special: the content of div.t-example.
    """
    sections: dict[str, str] = {}
    description_parts: list[str] = []
    example = ""

    current_section: Optional[str] = None
    current_parts: list[str] = []
    in_description = True

    # Tags to skip entirely when collecting description/section text
    _skip_classes = {"t-dcl-begin", "t-navbar"}

    for child in content_div.children:
        if not isinstance(child, Tag):
            # NavigableString
            text = str(child).strip()
            if text:
                if in_description:
                    description_parts.append(text)
                elif current_section:
                    current_parts.append(text)
            continue

        child_classes = set(child.get("class") or [])

        # Skip declaration tables, navbars (parsed separately)
        if child_classes & _skip_classes:
            continue

        # Handle h3 headings
        if child.name in ("h3", "h4", "h2"):
            # Flush previous section
            if current_section:
                sections[current_section] = _clean_text("\n".join(current_parts))
                current_parts = []

            heading_text = _clean_text(child.get_text(strip=True))
            current_section = heading_text
            in_description = False
            continue

        # Handle example div
        if "t-example" in child_classes:
            # Extract code from <pre> to avoid GeSHi span artifacts
            pre_tag = child.find("pre")
            if pre_tag:
                example = pre_tag.get_text(separator="")
            else:
                example = child.get_text(separator="\n")
            example = _clean_text(example)
            if current_section:
                sections[current_section] = _clean_text("\n".join(current_parts))
                current_parts = []
                current_section = None
            continue

        # Collect text from other elements
        text = child.get_text(separator="\n")
        if text.strip():
            if in_description:
                description_parts.append(text.strip())
            elif current_section:
                current_parts.append(text.strip())

    # Flush last section
    if current_section:
        sections[current_section] = _clean_text("\n".join(current_parts))

    description = _clean_text("\n\n".join(description_parts))
    return sections, example, description


def _parse_member_tables(content_div: Tag) -> list[MemberEntry]:
    """
    Parse t-dsc-begin tables that list member functions, types, etc.
    Returns list of MemberEntry.
    """
    members: list[MemberEntry] = []
    seen = set()  # deduplicate by name+url

    for table in content_div.find_all("table", class_="t-dsc-begin"):
        for row in table.find_all("tr"):
            tds = row.find_all("td")
            if len(tds) < 2:
                continue

            # First td: name + link
            name_td = tds[0]
            link = name_td.find("a")
            name = _clean_text(name_td.get_text(separator=" ", strip=True))
            url = link.get("href", "") if link else ""

            # Second td: description
            desc = _clean_text(tds[1].get_text(separator=" ", strip=True))

            key = (name, url)
            if key not in seen and name:
                seen.add(key)
                members.append(MemberEntry(name=name, url=url, description=desc))

    return members


def _parse_see_also(content_div: Tag) -> list[str]:
    """
    Parse the See also section: find the last h3 that contains 'see also',
    then grab the t-dsc-begin after it.
    """
    h3s = content_div.find_all("h3")
    see_also_h3 = None
    for h3 in h3s:
        if "see also" in h3.get_text().lower():
            see_also_h3 = h3
            # Keep going — use the last one

    if not see_also_h3:
        return []

    items: list[str] = []
    # Find the t-dsc-begin table after this h3
    table = see_also_h3.find_next("table", class_="t-dsc-begin")
    if table:
        for row in table.find_all("tr"):
            text = _clean_text(row.get_text(separator=" ", strip=True))
            if text:
                items.append(text)

    return items


def parse_page(html: str, filepath: str = "") -> CppRefEntry:
    """
    Parse a single cppreference HTML page into a CppRefEntry.
    """
    soup = BeautifulSoup(html, "html.parser")
    _remove_unwanted(soup)

    name = _page_title(soup)
    path = _page_path(filepath) if filepath else ""
    category = _page_category(filepath) if filepath else ""

    # Main content div
    content_div = soup.find("div", id="mw-content-text")
    if not content_div:
        content_div = soup.find("div", class_="mw-content-ltr") or soup.find("body") or soup

    # Remove the t-navbar (top navigation) from content
    for navbar in content_div.find_all("div", class_="t-navbar"):
        navbar.decompose()

    # Parse declaration table
    header, declarations = _parse_t_dcl_begin(content_div)

    # Parse sections (h3-headed) + example + description
    sections, example, description = _parse_sections(content_div)

    # Parse member tables
    members = _parse_member_tables(content_div)

    # Parse see also
    see_also = _parse_see_also(content_div)

    # Full cleaned text
    full_text = content_div.get_text(separator="\n")
    content = _clean_text(full_text)

    return CppRefEntry(
        name=name,
        path=path,
        category=category,
        header=header,
        declarations=declarations,
        description=description,
        sections=sections,
        example=example,
        see_also=see_also,
        members=members,
        content=content,
    )


# ---------------------------------------------------------------------------
# Book-level processing
# ---------------------------------------------------------------------------


def _iter_html_files(root_dir: str, categories: Optional[list[str]] = None):
    """
    Yield (filepath, html_content) for each .html file under root_dir.
    Skips overview pages (top-level category .html files) when
    categories is specified and the file is not a direct match.
    """
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Sort for deterministic output
        filenames.sort()
        for fname in filenames:
            if not fname.endswith(".html"):
                continue
            full_path = os.path.join(dirpath, fname)
            # Determine category
            rel = os.path.relpath(full_path, root_dir)
            cat = rel.split(os.sep)[0] if os.sep in rel else ""

            if categories and cat not in categories:
                continue

            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    html = f.read()
            except Exception as e:
                print(f"  Warning: failed to read {full_path}: {e}", file=sys.stderr)
                continue

            yield full_path, html


def parse_book(
    root_dir: str,
    categories: Optional[list[str]] = None,
    skip_overview: bool = False,
) -> list[CppRefEntry]:
    """
    Parse all HTML files in the book directory.
    """
    results: list[CppRefEntry] = []
    files_processed = 0
    errors = 0

    for filepath, html in _iter_html_files(root_dir, categories):
        try:
            entry = parse_page(html, filepath)
            results.append(entry)
            files_processed += 1
            if files_processed % 500 == 0:
                print(f"  Processed {files_processed} files...")
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  Error parsing {filepath}: {e}", file=sys.stderr)

    if errors:
        print(f"  {errors} parse errors (out of {files_processed + errors} files).")
    print(f"  Parsed {files_processed} pages successfully.")
    return results


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _member_to_dict(m: MemberEntry) -> dict:
    return {
        "name": m.name,
        "url": m.url,
        "description": m.description,
    }


def entries_to_json(entries: list[CppRefEntry]) -> list[dict]:
    """Convert parsed entries to a JSON-serializable list of dicts."""
    out = []
    for e in entries:
        d = {
            "name": e.name,
            "path": e.path,
            "category": e.category,
            "header": e.header,
            "declarations": e.declarations,
            "description": e.description,
            "sections": e.sections,
            "example": e.example,
            "see_also": e.see_also,
            "members": [_member_to_dict(m) for m in e.members],
            "content": e.content,
        }
        out.append(d)
    return out


def entries_to_flat_text(entries: list[CppRefEntry]) -> str:
    """Convert parsed entries to a human-readable flat text file."""
    lines: list[str] = []

    for e in entries:
        marker = "=" * 70
        lines.append(marker)

        # Title
        lines.append(f"Name: {e.name}")
        if e.path:
            lines.append(f"Path: {e.path}")
        if e.category:
            lines.append(f"Category: {e.category}")
        if e.header:
            lines.append(f"Header: {e.header}")

        lines.append(marker)
        lines.append("")

        # Declarations
        if e.declarations:
            lines.append("--- Declarations ---")
            for d in e.declarations:
                lines.append(f"  {d}")
            lines.append("")

        # Description
        if e.description:
            lines.append("--- Description ---")
            lines.append(e.description)
            lines.append("")

        # Sections
        for section_name, section_text in e.sections.items():
            lines.append(f"--- {section_name} ---")
            lines.append(section_text)
            lines.append("")

        # Members
        if e.members:
            lines.append("--- Members ---")
            for m in e.members:
                desc_str = f" — {m.description}" if m.description else ""
                lines.append(f"  * {m.name}{desc_str}")
            lines.append("")

        # Example
        if e.example:
            lines.append("--- Example ---")
            lines.append("```cpp")
            lines.append(e.example)
            lines.append("```")
            lines.append("")

        # See also
        if e.see_also:
            lines.append("--- See Also ---")
            for sa in e.see_also:
                lines.append(f"  * {sa}")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def print_stats(entries: list[CppRefEntry]) -> None:
    """Print summary statistics about the parsed book."""
    print(f"\n{'='*60}")
    print("Parse Summary")
    print(f"{'='*60}")
    print(f"  Total entries:         {len(entries)}")
    print(f"  With declarations:     {sum(1 for e in entries if e.declarations)}")
    print(f"  With description:      {sum(1 for e in entries if e.description)}")
    print(f"  With example:          {sum(1 for e in entries if e.example)}")
    print(f"  With see_also:         {sum(1 for e in entries if e.see_also)}")
    print(f"  With members:          {sum(1 for e in entries if e.members)}")
    print(f"  With sections:         {sum(1 for e in entries if e.sections)}")

    total_members = sum(len(e.members) for e in entries)
    print(f"  Total member entries:  {total_members}")

    # Per-category breakdown
    cats: dict[str, int] = {}
    for e in entries:
        cat = e.category or "(none)"
        cats[cat] = cats.get(cat, 0) + 1

    print(f"\n  Per-category breakdown:")
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"    {cat}: {count}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def prepare_root_dir(args) -> tuple[str, bool]:
    """
    Determine the root directory of the extracted book.
    Returns (root_dir, needs_cleanup).
    """
    needs_cleanup = False

    if args.dir:
        return args.dir, False

    # Determine tarball path
    tarball = args.book
    if not tarball:
        # Download
        dest = os.path.join(tempfile.gettempdir(), BOOK_FILENAME)
        if os.path.exists(dest):
            print(f"Using cached book at: {dest}")
            tarball = dest
        else:
            tarball = _fetch_book(BOOK_URL, dest)

    # Extract
    extract_dir = tempfile.mkdtemp(prefix="cppref_")
    print(f"Extracting to: {extract_dir}")
    with tarfile.open(tarball, "r:xz") as tf:
        tf.extractall(extract_dir, filter="data")
    print("  Extraction complete.")

    needs_cleanup = True
    # The extracted content is at extract_dir/reference/en/cpp/
    root = os.path.join(extract_dir, "reference", "en", "cpp")
    if not os.path.isdir(root):
        # maybe structure is different — try to find it
        for d in os.listdir(extract_dir):
            candidate = os.path.join(extract_dir, d)
            if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, "algorithm.html")):
                root = candidate
                break
    return root, needs_cleanup


def main():
    parser = argparse.ArgumentParser(
        description="C++ Reference Book Parser — extract structured API reference data "
                    "from the cppreference HTML book."
    )
    parser.add_argument(
        "--book", type=str, default=None,
        help=f"Path to the book tarball (.tar.xz). If not provided, downloads from {BOOK_URL}",
    )
    parser.add_argument(
        "--dir", type=str, default=None,
        help="Path to an already-extracted book directory (e.g. reference/en/cpp/). "
             "Skips download and extraction.",
    )
    parser.add_argument(
        "--outdir", "-o", type=str, default=DEFAULT_OUTDIR,
        help=f"Output directory (default: {DEFAULT_OUTDIR})",
    )
    parser.add_argument(
        "--format", "-f", type=str, choices=["json", "txt", "both"],
        default="json",
        help="Output format: json, txt, or both (default: json — TXT would be very large)",
    )
    parser.add_argument(
        "--categories", "-c", type=str, default=None,
        help="Comma-separated categories to parse (e.g. 'container,algorithm'). "
             "Default: all categories.",
    )
    parser.add_argument(
        "--stats-only", action="store_true",
        help="Only print statistics, do not write output files.",
    )
    parser.add_argument(
        "--keep-extracted", action="store_true",
        help="Do not remove the extracted temp directory after parsing.",
    )
    args = parser.parse_args()

    # --- Categories filter ---
    categories = None
    if args.categories:
        categories = [c.strip() for c in args.categories.split(",") if c.strip()]
        print(f"Filtering to categories: {categories}")

    # --- Prepare the book directory ---
    root_dir, needs_cleanup = prepare_root_dir(args)
    print(f"Book root directory: {root_dir}")

    if not os.path.isdir(root_dir):
        print(f"Error: directory not found: {root_dir}", file=sys.stderr)
        sys.exit(1)

    # --- Parse ---
    print("\nParsing book...")
    t0 = time.time()
    entries = parse_book(root_dir, categories=categories)
    elapsed = time.time() - t0
    print(f"  Parsed {len(entries)} entries in {elapsed:.1f}s.")

    print_stats(entries)

    # --- Cleanup ---
    if needs_cleanup and not args.keep_extracted:
        extract_root = os.path.dirname(os.path.dirname(root_dir))
        import shutil
        shutil.rmtree(extract_root, ignore_errors=True)
        print(f"\nCleaned up temp directory: {extract_root}")

    if args.stats_only:
        return

    # --- Write output ---
    os.makedirs(args.outdir, exist_ok=True)

    if args.format in ("json", "both"):
        json_path = os.path.join(args.outdir, "cppreference.json")
        data = entries_to_json(entries)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        file_size_mb = os.path.getsize(json_path) / (1024 * 1024)
        print(f"\nJSON written to: {json_path} ({file_size_mb:.1f} MB)")

    if args.format in ("txt", "both"):
        txt_path = os.path.join(args.outdir, "cppreference.txt")
        text = entries_to_flat_text(entries)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        file_size_mb = os.path.getsize(txt_path) / (1024 * 1024)
        print(f"TXT written to:  {txt_path} ({file_size_mb:.1f} MB)")

    print(f"\nDone. Output in: {args.outdir}/")


if __name__ == "__main__":
    main()
