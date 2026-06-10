"""
C++ Core Guidelines Parser
===========================
Parses https://isocpp.github.io/CppCoreGuidelines/CppCoreGuidelines into
structured JSON for downstream RAG ingestion.

The page is a single long HTML document with this hierarchy:
  h1 — major sections   (e.g. "In: Introduction", "F: Functions")
  h2 — subsections      (e.g. "F.call: Parameter passing")
  h3 — individual rules (e.g. "F.15: Prefer simple and conventional ways...")
  h5 — sub-headings within a rule: Reason, Example, Exception, Note, Enforcement

Outputs:
  - JSON: one record per heading (section, subsection, or rule), each with
          id, title, section path, content, code blocks, and sub-fields
          (reason, examples, exceptions, notes, enforcement).
  - TXT:  clean flat-text version for human reading / quick inspection.

Usage:
  # Download + parse, write JSON and TXT to default output dir
  python parse_cppcoreguidelines.py

  # Specify output directory
  python parse_cppcoreguidelines.py --outdir ./cpp_guidelines_output

  # JSON only
  python parse_cppcoreguidelines.py --format json

  # TXT only
  python parse_cppcoreguidelines.py --format txt

  # Also save the raw HTML for offline parsing
  python parse_cppcoreguidelines.py --save-html

  # Parse a local HTML file instead of fetching live
  python parse_cppcoreguidelines.py --html ./CppCoreGuidelines.html
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PAGE_URL = "https://isocpp.github.io/CppCoreGuidelines/CppCoreGuidelines"
BASE_URL = "https://isocpp.github.io"
REQUEST_TIMEOUT = 60  # the page is large
DEFAULT_OUTDIR = os.path.join(os.path.dirname(__file__), "cppcoreguidelines_output")

# Tags to completely remove before text extraction
REMOVE_TAGS = ["script", "style", "nav", "footer", "header", "noscript"]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CodeExample:
    """A single code example (good or bad) within a rule."""
    label: str = ""       # "Example", "Example, good", "Example, bad"
    code: str = ""        # the code snippet text
    description: str = "" # surrounding paragraph text


@dataclass
class ParsedHeading:
    """
    Represents one heading in the document (h1 section, h2 subsection, or h3 rule).
    """
    id: str                          # anchor name, e.g. "rf-inline", "s-functions"
    title: str                       # heading text, e.g. "F.5: If a function is..."
    level: int                       # 1, 2, or 3
    section: str = ""                # parent h1 section (e.g. "F: Functions")
    subsection: str = ""             # parent h2 subsection (e.g. "F.call: Parameter passing")
    rule_number: str = ""            # e.g. "F.5", "C.134" — extracted from title

    # --- Structured sub-fields (mainly populated for h3 rules) ---
    reason: str = ""
    examples: list[CodeExample] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    enforcement: str = ""
    see_also: list[str] = field(default_factory=list)

    # --- Full content ---
    content: str = ""                # clean plain text of everything under this heading
    code_blocks: list[str] = field(default_factory=list)  # raw code snippets found
    raw_html: str = ""               # raw inner HTML (optional, for debugging)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def fetch_page(url: str = PAGE_URL) -> str:
    """Fetch the C++ Core Guidelines page and return HTML."""
    print(f"Fetching {url} ...")
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    print(f"  Done ({len(resp.text)} chars).")
    return resp.text


def _make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _clean_text(text: str) -> str:
    """Collapse whitespace and strip."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_rule_number(title: str) -> str:
    """
    Try to extract a rule number from a title like:
      "F.5: If a function is very small..."  -> "F.5"
      "C.134: Ensure all non-const data..."   -> "C.134"
      "In.0: Don't panic!"                    -> "In.0"
      "NR.1: Don't insist that..."            -> "NR.1"
    """
    m = re.match(r"^([A-Za-z]+\.\d+)", title)
    if m:
        return m.group(1)
    return ""


def _extract_code_from_element(el: Tag) -> str:
    """Extract code text from a <pre><code> block."""
    code_tag = el.find("code")
    if code_tag:
        return code_tag.get_text()
    return el.get_text()


def _normalize_label(text: str) -> str:
    """Normalize h5 labels like 'Reason', 'Example, bad', etc."""
    text = text.strip()
    # Remove trailing number suffixes like "Reason (37)" from links
    text = re.sub(r"\s*\(\d+\)\s*$", "", text)
    return text


# ---------------------------------------------------------------------------
# Main parsing logic
# ---------------------------------------------------------------------------

def parse_document(html: str) -> list[ParsedHeading]:
    """
    Parse the full C++ Core Guidelines page into a list of ParsedHeading records.

    Walks the document hierarchically:
      - h1 defines the current section
      - h2 defines the current subsection
      - h3 defines an individual rule
      - h5 sub-headings within a rule are parsed into structured fields
    """
    soup = _make_soup(html)

    # --- Remove unwanted tags ---
    for tag_name in REMOVE_TAGS:
        for el in soup.find_all(tag_name):
            el.decompose()

    # Remove the sidebar
    sidebar = soup.find("div", class_="sidebar")
    if sidebar:
        sidebar.decompose()

    # Remove the GitHub banner
    banner = soup.find("div", class_="banner")
    if banner:
        banner.decompose()

    # Find the main content container
    content_div = soup.find("div", class_="content")
    if not content_div:
        # fallback: use the body
        content_div = soup.find("body") or soup

    # --- Walk all heading elements ---
    # BeautifulSoup doesn't easily give us a "next element until next heading of same/higher level",
    # so we collect all headings first, then walk the DOM to assign content.

    all_headings: list[Tag] = []
    heading_tags = {"h1", "h2", "h3"}
    for tag in content_div.find_all(heading_tags):
        all_headings.append(tag)

    if not all_headings:
        print("Warning: no headings found in the document.")
        return []

    results: list[ParsedHeading] = []
    current_section = ""
    current_subsection = ""

    for i, heading_tag in enumerate(all_headings):
        level = int(heading_tag.name[1])  # 1, 2, or 3

        # Get anchor id
        anchor = heading_tag.find("a", attrs={"name": True})
        heading_id = anchor["name"] if anchor else ""

        # Get title text (strip nested anchor/link tags)
        title = heading_tag.get_text(separator=" ", strip=True)
        title = _clean_text(title)

        # --- Extract content: everything between this heading and the next ---
        # Gather all sibling elements until the next heading of same or higher level.
        content_parts: list[str] = []
        code_blocks: list[str] = []
        raw_html_parts: list[str] = []

        sibling = heading_tag.next_sibling
        while sibling is not None:
            # Stop at the next heading of same or higher level
            if isinstance(sibling, Tag) and sibling.name in heading_tags:
                next_level = int(sibling.name[1])
                if next_level <= level:
                    break

            if isinstance(sibling, Tag):
                raw_html_parts.append(str(sibling))
                # Extract code blocks
                for pre in sibling.find_all("pre"):
                    code_text = _extract_code_from_element(pre)
                    if code_text.strip():
                        code_blocks.append(code_text.strip())

                # Extract text (use newline separator to preserve paragraph boundaries)
                text = sibling.get_text(separator="\n")
                if text.strip():
                    content_parts.append(text.strip())
            elif isinstance(sibling, NavigableString):
                text = str(sibling).strip()
                if text:
                    content_parts.append(text)

            sibling = sibling.next_sibling

        full_content = "\n\n".join(content_parts)
        full_content = _clean_text(full_content)
        raw_html = "\n".join(raw_html_parts)

        # --- Determine section / subsection context ---
        if level == 1:
            current_section = title
            current_subsection = ""
        elif level == 2:
            current_subsection = title

        # --- Extract structured sub-fields (for h3 rules, and some h1/h2) ---
        reason = ""
        examples: list[CodeExample] = []
        exceptions: list[str] = []
        notes: list[str] = []
        enforcement = ""
        see_also: list[str] = []

        if level == 3:
            # For h3 rules, parse content for h5 sub-headings:
            #   Reason, Example, Exception, Note, Enforcement
            current_label = ""
            current_text_parts: list[str] = []
            current_code = ""
            current_code_label = ""

            # Build a mini-soup of the content portion
            content_soup = _make_soup(f"<div>{raw_html}</div>")

            for child in content_soup.find("div").children:  # type: ignore[union-attr]
                if isinstance(child, Tag) and child.name == "h5":
                    # Flush previous section
                    text = _clean_text("\n".join(current_text_parts))
                    label_lower = current_label.lower()

                    if label_lower.startswith("reason"):
                        reason = text
                    elif label_lower.startswith("example"):
                        examples.append(CodeExample(
                            label=current_label,
                            code=current_code,
                            description=text,
                        ))
                    elif label_lower.startswith("exception"):
                        if text:
                            exceptions.append(text)
                    elif label_lower.startswith("note"):
                        if text:
                            notes.append(text)
                    elif label_lower.startswith("enforcement"):
                        enforcement = text

                    # Start new section
                    current_label = _normalize_label(child.get_text(strip=True))
                    current_text_parts = []
                    current_code = ""
                    current_code_label = current_label
                elif isinstance(child, Tag):
                    # Check for code blocks
                    pre_tags = child.find_all("pre") if child.name != "pre" else [child]
                    for pre in pre_tags:
                        code_text = _extract_code_from_element(pre)
                        if code_text.strip():
                            if current_code:
                                current_code += "\n\n"
                            current_code += code_text.strip()
                    text = child.get_text(separator="\n")
                    if text.strip():
                        current_text_parts.append(text.strip())
                elif isinstance(child, NavigableString):
                    text = str(child).strip()
                    if text:
                        current_text_parts.append(text)

            # Flush last section
            text = _clean_text("\n".join(current_text_parts))
            label_lower = current_label.lower()
            if label_lower.startswith("reason"):
                reason = text
            elif label_lower.startswith("example"):
                examples.append(CodeExample(
                    label=current_label,
                    code=current_code,
                    description=text,
                ))
            elif label_lower.startswith("exception"):
                if text:
                    exceptions.append(text)
            elif label_lower.startswith("note"):
                if text:
                    notes.append(text)
            elif label_lower.startswith("enforcement"):
                enforcement = text

            # Also parse "See also" from the full content
            see_also_pattern = re.findall(
                r'\*\*See also\*\*:?\s*\n((?:\s*[-*]\s*[^\n]+\n?)+)',
                full_content,
                re.IGNORECASE
            )
            for block in see_also_pattern:
                for line in block.strip().split("\n"):
                    line = line.strip().lstrip("-*").strip()
                    if line:
                        see_also.append(line)

        rule_number = _extract_rule_number(title)

        parsed = ParsedHeading(
            id=heading_id,
            title=title,
            level=level,
            section=current_section if level > 1 else "",
            subsection=current_subsection if level > 2 else "",
            rule_number=rule_number,
            reason=reason,
            examples=examples,
            exceptions=exceptions,
            notes=notes,
            enforcement=enforcement,
            see_also=see_also,
            content=full_content,
            code_blocks=code_blocks,
            raw_html="" if "--debug" not in sys.argv else raw_html,
        )
        results.append(parsed)

    return results


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _code_example_to_dict(ce: CodeExample) -> dict:
    return {
        "label": ce.label,
        "code": ce.code,
        "description": ce.description,
    }


def headings_to_json(headings: list[ParsedHeading]) -> list[dict]:
    """Convert parsed headings to a JSON-serializable list of dicts."""
    out = []
    for h in headings:
        d = {
            "id": h.id,
            "title": h.title,
            "level": h.level,
            "section": h.section,
            "subsection": h.subsection,
            "rule_number": h.rule_number,
            "reason": h.reason,
            "examples": [_code_example_to_dict(e) for e in h.examples],
            "exceptions": h.exceptions,
            "notes": h.notes,
            "enforcement": h.enforcement,
            "see_also": h.see_also,
            "content": h.content,
            "code_blocks": h.code_blocks,
        }
        out.append(d)
    return out


def headings_to_flat_text(headings: list[ParsedHeading]) -> str:
    """Convert parsed headings to a human-readable flat text file."""
    lines: list[str] = []
    level_markers = {1: "=", 2: "-", 3: "~"}

    for h in headings:
        marker = level_markers.get(h.level, "-") * 70

        # Section path
        path_parts = []
        if h.section:
            path_parts.append(h.section)
        if h.subsection:
            path_parts.append(h.subsection)
        path = " > ".join(path_parts) if path_parts else ""

        lines.append(marker)
        if path:
            lines.append(f"[{path}]")
        lines.append(f"{h.title}")
        if h.rule_number:
            lines.append(f"Rule: {h.rule_number}")
        if h.id:
            lines.append(f"Anchor: #{h.id}")
        lines.append(marker)
        lines.append("")

        if h.reason:
            lines.append("--- Reason ---")
            lines.append(h.reason)
            lines.append("")

        if h.examples:
            for ex in h.examples:
                label = ex.label or "Example"
                lines.append(f"--- {label} ---")
                if ex.description:
                    lines.append(ex.description)
                    lines.append("")
                if ex.code:
                    lines.append("```cpp")
                    lines.append(ex.code)
                    lines.append("```")
                    lines.append("")

        if h.exceptions:
            lines.append("--- Exceptions ---")
            for exc in h.exceptions:
                lines.append(f"  * {exc}")
            lines.append("")

        if h.notes:
            lines.append("--- Notes ---")
            for note in h.notes:
                lines.append(f"  * {note}")
            lines.append("")

        if h.enforcement:
            lines.append("--- Enforcement ---")
            lines.append(h.enforcement)
            lines.append("")

        if h.see_also:
            lines.append("--- See Also ---")
            for sa in h.see_also:
                lines.append(f"  * {sa}")
            lines.append("")

        if h.content and not any([h.reason, h.examples, h.exceptions,
                                   h.notes, h.enforcement, h.see_also]):
            # For headings without structured sub-fields, output raw content
            lines.append(h.content)
            lines.append("")

        if h.code_blocks and not h.examples:
            lines.append("--- Code Blocks ---")
            for cb in h.code_blocks:
                lines.append("```cpp")
                lines.append(cb)
                lines.append("```")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def print_stats(headings: list[ParsedHeading]) -> None:
    """Print summary statistics about the parsed document."""
    h1_count = sum(1 for h in headings if h.level == 1)
    h2_count = sum(1 for h in headings if h.level == 2)
    h3_count = sum(1 for h in headings if h.level == 3)
    rules_count = sum(1 for h in headings if h.rule_number)
    with_reason = sum(1 for h in headings if h.reason)
    with_enforcement = sum(1 for h in headings if h.enforcement)
    with_examples = sum(1 for h in headings if h.examples)
    total_code_blocks = sum(len(h.code_blocks) for h in headings)

    print(f"\n{'='*60}")
    print(f"Parse Summary")
    print(f"{'='*60}")
    print(f"  H1 sections:      {h1_count}")
    print(f"  H2 subsections:   {h2_count}")
    print(f"  H3 rules:         {h3_count}")
    print(f"  Total headings:   {len(headings)}")
    print(f"  With rule number: {rules_count}")
    print(f"  With reason:      {with_reason}")
    print(f"  With enforcement: {with_enforcement}")
    print(f"  With examples:    {with_examples}")
    print(f"  Total code blocks:{total_code_blocks}")

    # Per-section breakdown
    sections: dict[str, int] = {}
    for h in headings:
        if h.level == 1:
            continue
        sec = h.section or "(no section)"
        sections[sec] = sections.get(sec, 0) + 1

    print(f"\n  Per-section breakdown:")
    for sec, count in sections.items():
        print(f"    {sec}: {count}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="C++ Core Guidelines Parser — extract structured data from "
                    "https://isocpp.github.io/CppCoreGuidelines/CppCoreGuidelines"
    )
    parser.add_argument(
        "--html", type=str, default=None,
        help="Path to a local HTML file (if already downloaded). "
             "If not provided, fetches from the live URL."
    )
    parser.add_argument(
        "--outdir", "-o", type=str, default=DEFAULT_OUTDIR,
        help=f"Output directory (default: {DEFAULT_OUTDIR})"
    )
    parser.add_argument(
        "--format", "-f", type=str, choices=["json", "txt", "both"],
        default="both",
        help="Output format: json, txt, or both (default: both)"
    )
    parser.add_argument(
        "--save-html", action="store_true",
        help="Also save the raw HTML file to the output directory."
    )
    parser.add_argument(
        "--stats-only", action="store_true",
        help="Only print statistics, do not write output files."
    )
    args = parser.parse_args()

    # --- Fetch or load HTML ---
    if args.html:
        print(f"Loading HTML from: {args.html}")
        with open(args.html, "r", encoding="utf-8") as f:
            html = f.read()
        print(f"  Loaded {len(html)} chars.")
    else:
        html = fetch_page(PAGE_URL)

    # --- Save raw HTML if requested ---
    if args.save_html:
        os.makedirs(args.outdir, exist_ok=True)
        html_path = os.path.join(args.outdir, "CppCoreGuidelines.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Saved raw HTML to: {html_path}")

    # --- Parse ---
    print("\nParsing document...")
    t0 = time.time()
    headings = parse_document(html)
    elapsed = time.time() - t0
    print(f"  Parsed {len(headings)} headings in {elapsed:.2f}s.")

    print_stats(headings)

    if args.stats_only:
        return

    # --- Write output ---
    os.makedirs(args.outdir, exist_ok=True)

    if args.format in ("json", "both"):
        json_path = os.path.join(args.outdir, "cppcoreguidelines.json")
        data = headings_to_json(headings)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        file_size_kb = os.path.getsize(json_path) / 1024
        print(f"\nJSON written to: {json_path} ({file_size_kb:.1f} KB)")

    if args.format in ("txt", "both"):
        txt_path = os.path.join(args.outdir, "cppcoreguidelines.txt")
        text = headings_to_flat_text(headings)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        file_size_kb = os.path.getsize(txt_path) / 1024
        print(f"TXT written to:  {txt_path} ({file_size_kb:.1f} KB)")

    print(f"\nDone. Output in: {args.outdir}/")


if __name__ == "__main__":
    main()
