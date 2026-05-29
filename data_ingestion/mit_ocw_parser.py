"""
MIT OCW Course Parser
=====================
Parses MIT OCW course pages (from mitocw.ups.edu.ec mirror) into clean plain text.
Supports:
  - Parsing a lectures-and-assignments index page to discover all lecture links
  - Parsing individual lecture sub-pages to extract text content
  - Crawling an entire course and saving each page as a .txt file

Usage:
  # Parse a single page and print to stdout
  python mit_ocw_parser.py --url "https://mitocw.ups.edu.ec/courses/.../lectures-and-assignments/"

  # Crawl an entire course (index page + all lecture sub-pages) to output dir
  python mit_ocw_parser.py --url "https://mitocw.ups.edu.ec/courses/.../lectures-and-assignments/" --crawl --outdir ./output

  # Parse a single page and save to file
  python mit_ocw_parser.py --url "https://mitocw.ups.edu.ec/courses/.../some-page/" --outdir ./output
"""

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class LectureLink:
    """A lecture entry discovered on an index page."""
    title: str
    url: str                          # absolute URL
    lecture_number: Optional[int] = None
    is_pdf: bool = False
    is_subpage: bool = False


@dataclass
class ParsedPage:
    """Result of parsing a single page."""
    url: str
    title: str
    breadcrumb: str = ""
    text: str = ""                    # clean plain text
    links: list[dict] = field(default_factory=list)   # embedded resource links


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://mitocw.ups.edu.ec"
REQUEST_TIMEOUT = 30
DELAY_BETWEEN_REQUESTS = 0.5  # seconds, to be polite to the server

# Elements to completely remove before text extraction
REMOVE_TAGS = ["script", "style", "nav", "footer", "header", "noscript"]


# ---------------------------------------------------------------------------
# Core parsing functions
# ---------------------------------------------------------------------------

def fetch_page(url: str) -> str:
    """Fetch a page and return its HTML content."""
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    # The MIT OCW mirror often doesn't declare charset in headers;
    # let requests guess from content.
    resp.encoding = resp.apparent_encoding
    return resp.text


def _make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _clean_text(text: str) -> str:
    """Collapse whitespace and strip."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _abs_url(href: str, base: str = BASE_URL) -> str:
    """Resolve a possibly-relative href to an absolute URL."""
    return urljoin(base, href)


def _is_same_course(href: str, course_prefix: str) -> bool:
    """Check if a link belongs to the same course."""
    return course_prefix in href


def _extract_lecture_number(title: str) -> Optional[int]:
    """Try to extract a lecture number from a title string."""
    m = re.search(r"[Ll]ecture\s*(\d+)", title)
    if m:
        return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Page title & breadcrumb
# ---------------------------------------------------------------------------

def _extract_page_title(soup: BeautifulSoup) -> str:
    """Extract page title from the <h1 class='title'> element."""
    h1 = soup.find("h1", class_="title")
    if h1:
        return h1.get_text(strip=True)
    # fallback to <title> tag
    title_tag = soup.find("title")
    if title_tag:
        t = title_tag.get_text(strip=True)
        # strip " | MIT OpenCourseWare" suffix
        t = re.sub(r"\s*\|.*$", "", t)
        return t
    return ""


def _extract_breadcrumb(soup: BeautifulSoup) -> str:
    """Extract breadcrumb text from the breadcrumb nav."""
    bc = soup.find("nav", id="breadcrumb")
    if bc:
        text = bc.get_text(separator=" ", strip=True)
        # Collapse any stray whitespace
        text = re.sub(r"\s+", " ", text).strip()
        # Remove the trailing "»" if present
        text = text.rstrip("»").strip()
        return text
    return ""


# ---------------------------------------------------------------------------
# Index page parsing
# ---------------------------------------------------------------------------

def parse_index_page(html: str, page_url: str) -> tuple[str, list[LectureLink]]:
    """
    Parse a lectures-and-assignments index page.

    Returns:
        page_title: The page title (e.g. "Lectures and Assignments")
        lectures: List of LectureLink objects for sub-pages and direct PDFs
    """
    soup = _make_soup(html)
    title = _extract_page_title(soup)

    main = soup.find("main", id="course_inner_section")
    if not main:
        return title, []

    # Determine course prefix from page_url for filtering
    # e.g. from ".../6-s096-introduction-to-c-and-c-january-iap-2013/lectures-and-assignments/"
    parsed = urlparse(page_url)
    course_prefix = parsed.path.rsplit("/lectures-and-assignments", 1)[0]
    if not course_prefix.endswith("/"):
        course_prefix += "/"

    lectures: list[LectureLink] = []
    seen_urls: set[str] = set()

    for a_tag in main.find_all("a", href=True):
        href = a_tag["href"].strip()
        abs_href = _abs_url(href, page_url)
        if abs_href in seen_urls:
            continue
        seen_urls.add(abs_href)

        link_text = a_tag.get_text(strip=True)

        is_pdf = href.lower().endswith(".pdf")
        is_zip = href.lower().endswith(".zip")
        # Sub-pages must be under the lectures-and-assignments/ path
        # (excludes links to other course sections like final-project, syllabus, etc.)
        is_subpage = not is_pdf and not is_zip and "/lectures-and-assignments/" in href
        is_direct_file = is_pdf or is_zip

        # Skip non-lecture links and external links
        if not is_direct_file and not is_subpage:
            continue

        # Skip the index page self-link
        if abs_href.rstrip("/") == page_url.rstrip("/"):
            continue

        lecture_num = _extract_lecture_number(link_text)

        lectures.append(LectureLink(
            title=link_text,
            url=abs_href,
            lecture_number=lecture_num,
            is_pdf=is_pdf,
            is_subpage=is_subpage,
        ))

    return title, lectures


# ---------------------------------------------------------------------------
# Lecture sub-page parsing
# ---------------------------------------------------------------------------

def parse_lecture_page(html: str, page_url: str) -> ParsedPage:
    """
    Parse a single lecture sub-page into clean text.

    Extracts the main content area, removes navigation/sidebar/ads,
    and returns clean plain text plus any embedded resource links.
    """
    soup = _make_soup(html)
    title = _extract_page_title(soup)
    breadcrumb = _extract_breadcrumb(soup)

    # ---- Remove non-content elements ----
    for tag_name in REMOVE_TAGS:
        for el in soup.find_all(tag_name):
            el.decompose()

    # Remove the course sidebar nav
    course_nav = soup.find("nav", id="course_nav")
    if course_nav:
        course_nav.decompose()

    # Remove breadcrumb (already captured)
    bc = soup.find("nav", id="breadcrumb")
    if bc:
        bc.decompose()

    # ---- Extract main content ----
    main = soup.find("main", id="course_inner_section")
    if not main:
        return ParsedPage(url=page_url, title=title, breadcrumb=breadcrumb, text="")

    # Collect resource links (PDFs, ZIPs) before flattening text
    resource_links: list[dict] = []
    for a_tag in main.find_all("a", href=True):
        href = a_tag["href"].strip()
        abs_href = _abs_url(href, page_url)
        link_text = a_tag.get_text(strip=True)
        resource_links.append({
            "text": link_text,
            "url": abs_href,
            "type": "pdf" if href.lower().endswith(".pdf")
                    else "zip" if href.lower().endswith(".zip")
                    else "page",
        })

    # Get text from main content area. Use separator="\n" to preserve
    # paragraph-level separation.
    raw_text = main.get_text(separator="\n")

    # Clean up: remove lines that are just whitespace, collapse multiple newlines
    lines = raw_text.split("\n")
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped:
            clean_lines.append(stripped)

    text = "\n".join(clean_lines)
    text = _clean_text(text)

    return ParsedPage(
        url=page_url,
        title=title,
        breadcrumb=breadcrumb,
        text=text,
        links=resource_links,
    )


# ---------------------------------------------------------------------------
# High-level parsing: auto-detect page type
# ---------------------------------------------------------------------------

def parse_page(html: str, page_url: str) -> tuple[str, list[LectureLink], ParsedPage | None]:
    """
    Auto-detect page type and parse accordingly.

    Returns:
        page_title: str
        lectures: list of LectureLink (only populated for index pages)
        parsed: ParsedPage | None (populated for lecture sub-pages and non-index pages)
    """
    soup = _make_soup(html)
    title = _extract_page_title(soup)

    main = soup.find("main", id="course_inner_section")
    if not main:
        return title, [], None

    # Detect if this is a lectures-and-assignments index page
    # by checking if the URL path ends with 'lectures-and-assignments'
    parsed_url = urlparse(page_url)
    is_index = parsed_url.path.rstrip("/").endswith("lectures-and-assignments")

    # Also check the page title as a heuristic
    if title.lower().startswith("lectures and assignments"):
        is_index = True

    if is_index:
        page_title, lectures = parse_index_page(html, page_url)
        return page_title, lectures, None
    else:
        parsed = parse_lecture_page(html, page_url)
        return title, [], parsed


# ---------------------------------------------------------------------------
# Crawler: crawl a full course
# ---------------------------------------------------------------------------

def crawl_course(index_url: str, outdir: str) -> list[str]:
    """
    Crawl an entire course starting from the lectures-and-assignments index page.

    1. Fetch & parse the index page to discover all lecture links
    2. Fetch & parse each lecture sub-page
    3. Save each page as a .txt file

    Returns:
        List of paths to saved files.
    """
    os.makedirs(outdir, exist_ok=True)
    saved_files: list[str] = []

    print(f"[1/2] Fetching index page: {index_url}")
    html = fetch_page(index_url)
    title, lectures = parse_index_page(html, index_url)

    print(f"      Found {len(lectures)} lecture links on index page.")
    print(f"      Page title: {title}")

    # Save index page text
    parsed_index = parse_lecture_page(html, index_url)
    index_text = f"TITLE: {parsed_index.title}\n"
    index_text += f"BREADCRUMB: {parsed_index.breadcrumb}\n"
    index_text += "=" * 70 + "\n\n"
    index_text += parsed_index.text

    safe_name = "00_index"
    filepath = os.path.join(outdir, f"{safe_name}.txt")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(index_text)
    saved_files.append(filepath)
    print(f"      Saved: {filepath}")

    # Only crawl sub-pages (not direct PDFs)
    subpages = [lec for lec in lectures if lec.is_subpage]

    print(f"\n[2/2] Crawling {len(subpages)} lecture sub-pages...")
    for i, lec in enumerate(subpages, 1):
        print(f"      [{i}/{len(subpages)}] {lec.title}")
        try:
            html = fetch_page(lec.url)
            parsed = parse_lecture_page(html, lec.url)

            text = f"TITLE: {parsed.title}\n"
            text += f"BREADCRUMB: {parsed.breadcrumb}\n"
            text += f"SOURCE: {parsed.url}\n"
            text += "=" * 70 + "\n\n"
            text += parsed.text

            if parsed.links:
                text += "\n\n--- Resource Links ---\n"
                for link in parsed.links:
                    text += f"  [{link['type'].upper()}] {link['text']}: {link['url']}\n"

            # Generate a safe filename from the URL slug
            slug = lec.url.rstrip("/").rsplit("/", 1)[-1]
            # Truncate if too long
            slug = slug[:80] if len(slug) > 80 else slug
            filepath = os.path.join(outdir, f"{i:02d}_{slug}.txt")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(text)
            saved_files.append(filepath)
            print(f"            -> {filepath}")

        except Exception as e:
            print(f"            ERROR: {e}")

        time.sleep(DELAY_BETWEEN_REQUESTS)

    # Also save a summary manifest
    manifest_path = os.path.join(outdir, "manifest.txt")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(f"Course Index: {index_url}\n")
        f.write(f"Saved files:\n")
        for fp in saved_files:
            f.write(f"  {fp}\n")
    saved_files.append(manifest_path)

    print(f"\nDone! {len(saved_files)} files saved to {outdir}/")
    return saved_files


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="MIT OCW Course Parser - extract plain text from course pages"
    )
    parser.add_argument(
        "--url", "-u", type=str, required=True,
        help="URL of the page to parse (index or individual lecture page)"
    )
    parser.add_argument(
        "--crawl", "-c", action="store_true",
        help="Crawl the entire course (starting from an index page)"
    )
    parser.add_argument(
        "--outdir", "-o", type=str, default="./mit_ocw_output",
        help="Output directory for saved text files (default: ./mit_ocw_output)"
    )
    args = parser.parse_args()

    if args.crawl:
        saved = crawl_course(args.url, args.outdir)
        print(f"\nCrawl complete. {len(saved)} files written.")
    else:
        print(f"Fetching: {args.url}")
        html = fetch_page(args.url)
        page_title, lectures, parsed_page = parse_page(html, args.url)

        if lectures:
            # Index page
            print(f"\nPage title: {page_title}")
            print(f"Found {len(lectures)} links:")
            for lec in lectures:
                kind = "PDF" if lec.is_pdf else "sub-page"
                num = f" (Lecture {lec.lecture_number})" if lec.lecture_number else ""
                print(f"  [{kind}] {lec.title}{num}")
                print(f"         {lec.url}")

        if parsed_page:
            print(f"\n{'='*70}")
            print(f"TITLE: {parsed_page.title}")
            print(f"BREADCRUMB: {parsed_page.breadcrumb}")
            print(f"SOURCE: {parsed_page.url}")
            print(f"{'='*70}\n")
            print(parsed_page.text)

            if parsed_page.links:
                print(f"\n--- Resource Links ---")
                for link in parsed_page.links:
                    print(f"  [{link['type'].upper()}] {link['text']}: {link['url']}")

            if args.outdir:
                os.makedirs(args.outdir, exist_ok=True)
                # Derive filename from URL
                slug = args.url.rstrip("/").rsplit("/", 1)[-1] or "page"
                filepath = os.path.join(args.outdir, f"{slug}.txt")
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(f"TITLE: {parsed_page.title}\n")
                    f.write(f"BREADCRUMB: {parsed_page.breadcrumb}\n")
                    f.write(f"SOURCE: {parsed_page.url}\n")
                    f.write("=" * 70 + "\n\n")
                    f.write(parsed_page.text)
                    if parsed_page.links:
                        f.write("\n\n--- Resource Links ---\n")
                        for link in parsed_page.links:
                            f.write(f"  [{link['type'].upper()}] {link['text']}: {link['url']}\n")
                print(f"\nSaved to: {filepath}")


if __name__ == "__main__":
    main()
