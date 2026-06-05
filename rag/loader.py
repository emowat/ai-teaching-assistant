"""
Course material loader: reads from raw_data/ (future: S3), chunks by slide,
classifies into DocCategory, embeds, and returns Qdrant PointStructs.

Data sources:
  - lecture_text/*.json       →  structured slides ({page, section, text, has_code})
  - mit_ocw_output/syllabus.txt →  course syllabus (authoritative boundaries)
  - lecture_text/assignment*_solution.json →  assignment reference solutions

Chunking strategy:
  - One slide = one chunk (natural boundary, already well-scoped).
  - Slides in the same section are NOT merged — keeping them granular improves
    retrieval precision for targeted Socratic nudges.

Week mapping:
  - Lecture N → week N (1-indexed, matching SYLLABUS_MATRIX).
  - Syllabus spans all weeks (one doc per week).

Category classification heuristic:
  - Syllabus file                          → Syllabus
  - Assignment solutions                   → Supplementary
  - Slide text contains imperative/caution  → Strict_Rules
    keywords (must, always, never, remember, ensure, do not, avoid, forbidden, be careful)
  - Everything else                        → Pedagogical_Context

The change in this file is intentionally narrow: chunk IDs are now
deterministic instead of random so the indexing layer can safely upsert the
same document repeatedly without creating duplicates in Qdrant Cloud.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from rag.schemas import ChunkPayload, DocCategory, SourceDomain


# ---------------------------------------------------------------------------
# Week mapping: lecture file → week
# ---------------------------------------------------------------------------
_LECTURE_WEEK_MAP: dict[str, int] = {
    "01_lecture_1_compilation_pipeline": 1,
    "02_lecture_2_core_c": 2,
    "03_lecture_3_c_memory_management": 3,
    "04_lecture_4_data_structures_debugging": 4,
    "05_lecture_5_c_introduction_classes_and_templates": 5,
    "06_lecture_6_c_inheritance": 6,
    "07_lecture_7_parent_destructors": 7,
    "08_lecture_8_standard_template_library": 8,
}


def _resolve_week(filename: str) -> int:
    """Match a lecture filename to its week number."""
    for key, week in _LECTURE_WEEK_MAP.items():
        if key in filename:
            return week
    return 1  # fallback


# ---------------------------------------------------------------------------
# Category classification
# ---------------------------------------------------------------------------

# Keywords that suggest a slide is a Strict_Rule rather than pedagogical
_STRICT_RULE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(must|always|never)\b", re.IGNORECASE),
    re.compile(r"\b(remember to|ensure that|be careful|make sure)\b", re.IGNORECASE),
    re.compile(r"\b(do not|don't|avoid|forbidden|prohibited)\b", re.IGNORECASE),
    re.compile(r"\b(critical|mandatory|required|essential)\b", re.IGNORECASE),
]


def classify_category(text: str, has_code: bool, source: str) -> DocCategory:
    """
    Heuristic classification of a chunk into DocCategory.

    Rules (ordered by priority):
      1. Syllabus source → Syllabus
      2. Assignment solution source → Supplementary
      3. Text matches strict-rule keywords → Strict_Rules
      4. Otherwise → Pedagogical_Context
    """
    if source == "syllabus":
        return DocCategory.SYLLABUS
    if source == "assignment_solution":
        return DocCategory.SUPPLEMENTARY

    # Only lecture slides proceed to keyword check
    for pattern in _STRICT_RULE_PATTERNS:
        if pattern.search(text):
            return DocCategory.STRICT_RULES

    return DocCategory.PEDAGOGICAL_CONTEXT


# ---------------------------------------------------------------------------
# Priority mapping
# ---------------------------------------------------------------------------
CATEGORY_PRIORITY: dict[DocCategory, int] = {
    DocCategory.SYLLABUS: 1,
    DocCategory.STRICT_RULES: 1,
    DocCategory.PEDAGOGICAL_CONTEXT: 2,
    DocCategory.SUPPLEMENTARY: 3,
}


_CHUNK_NAMESPACE = uuid.UUID("58dbf568-51bb-4d4e-8cf9-c6a8a797d065")


def _stable_chunk_id(*parts: object) -> str:
    """Return a deterministic UUID so repeated indexing upserts the same point.

    The namespace is fixed and the input parts are chosen from stable document
    attributes, which means the same source material will always produce the
    same Qdrant point ID across runs.
    """
    normalized = "::".join(str(part) for part in parts)
    return str(uuid.uuid5(_CHUNK_NAMESPACE, normalized))


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

class CourseMaterialLoader:
    """
    Loads course materials from raw_data/, chunks by slide, classifies,
    and yields ChunkPayload objects ready for embedding + indexing.

    Usage:
        loader = CourseMaterialLoader("raw_data")
        chunks = loader.load_all()
        # Then embed with SentenceTransformer and upsert to Qdrant.
    """

    def __init__(self, raw_data_path: str | Path):
        self.raw_data = Path(raw_data_path)
        if not self.raw_data.exists():
            raise FileNotFoundError(f"raw_data path not found: {self.raw_data}")

        self.lecture_text_dir = self.raw_data / "lecture_text"
        self.syllabus_path = self.raw_data / "mit_ocw_output" / "syllabus.txt"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_all(self) -> list[ChunkPayload]:
        """Load all available sources and return chunk payloads."""
        chunks: list[ChunkPayload] = []

        chunks.extend(self._load_lecture_slides())
        chunks.extend(self._load_syllabus())
        chunks.extend(self._load_assignment_solutions())

        print(f"Loaded {len(chunks)} chunks total.")
        return chunks

    # ------------------------------------------------------------------
    # Source loaders
    # ------------------------------------------------------------------

    def _load_lecture_slides(self) -> list[ChunkPayload]:
        """Load all lecture_text/*.json → one ChunkPayload per slide."""
        chunks: list[ChunkPayload] = []

        json_files = sorted(self.lecture_text_dir.glob("*.json"))
        # Exclude assignment solution files — handled separately
        json_files = [f for f in json_files if "assignment" not in f.name.lower()]

        for json_file in json_files:
            week = _resolve_week(json_file.name)
            file_chunks = self._parse_lecture_json(json_file, week)
            chunks.extend(file_chunks)
            print(f"  {json_file.name}: {len(file_chunks)} slides → week {week}")

        return chunks

    def _load_syllabus(self) -> list[ChunkPayload]:
        """Load syllabus.txt → one chunk per week (mirrors SYLLABUS_MATRIX)."""
        if not self.syllabus_path.exists():
            print(f"  WARNING: syllabus.txt not found at {self.syllabus_path}")
            return []

        raw_text = self.syllabus_path.read_text(encoding="utf-8")
        # Strip the TITLE/BREADCRUMB/SOURCE headers
        content = _strip_headers(raw_text)

        # Create one chunk per week from the syllabus content + matrix metadata
        chunks: list[ChunkPayload] = []
        for week, info in SYLLABUS_MATRIX.items():
            # A stable ID is important here because the same syllabus page is
            # indexed every time the collection is rebuilt or refreshed.
            chunk_id = _stable_chunk_id("syllabus", week, info["name"])
            syllabus_content = (
                f"Week: {week} - {info['name']}\n"
                f"Allowed: {info['allowed']}\n"
                f"Forbidden: {info['forbidden']}\n\n"
                f"Course Description: {content[:500]}"
            )
            chunks.append(ChunkPayload(
                chunk_id=chunk_id,
                content=syllabus_content,
                week=week,
                category=DocCategory.SYLLABUS,
                topic="syllabus",
                priority=1,
                source_domain=SourceDomain.MIT_OCW_SYLLABUS,
                source_type="syllabus_page",
                page_number=None,
            ))

        print(f"  syllabus.txt: {len(chunks)} week entries")
        return chunks

    def _load_assignment_solutions(self) -> list[ChunkPayload]:
        """Load assignment solution JSONs → supplementary reference chunks."""
        chunks: list[ChunkPayload] = []

        for json_file in sorted(self.lecture_text_dir.glob("assignment*_solution.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                print(f"  WARNING: could not parse {json_file.name}")
                continue

            # Assign to a week based on filename or default to mid-course
            week = 4  # assignments typically relate to mid-course material
            for slide in data:
                text = str(slide.get("text", ""))
                if not text.strip():
                    continue

                # Assignment solution chunks are keyed by file/page/content so
                # re-running the bootstrap process updates the same record.
                chunk_id = _stable_chunk_id(
                    "assignment_solution",
                    json_file.name,
                    slide.get("page"),
                    text[:2000],
                )
                chunks.append(ChunkPayload(
                    chunk_id=chunk_id,
                    content=text[:2000],  # cap long code solutions
                    week=week,
                    category=DocCategory.SUPPLEMENTARY,
                    topic="assignment_solution",
                    priority=3,
                    source_domain=SourceDomain.MIT_OCW_ASSIGNMENT,
                    source_type="assignment_solution",
                    page_number=slide.get("page"),
                ))

            print(f"  {json_file.name}: {len(data)} pages → {len(chunks)} chunks")

        return chunks

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_lecture_json(self, json_file: Path, week: int) -> list[ChunkPayload]:
        """Parse a single lecture JSON file → ChunkPayload per slide."""
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"  WARNING: could not parse {json_file.name}")
            return []

        chunks: list[ChunkPayload] = []
        for slide in data:
            text = str(slide.get("text", "")).strip()
            if not text:
                continue

            has_code = bool(slide.get("has_code", False))
            section = str(slide.get("section", ""))
            page = slide.get("page")

            category = classify_category(text, has_code, source="lecture")
            # Lecture chunks also need deterministic IDs so each slide remains
            # a single logical record in the vector store even after retries.
            chunk_id = _stable_chunk_id("lecture", json_file.name, page, section, text[:2000])

            # Prefix with section context for better retrieval
            content = f"[{section}] {text}" if section else text

            chunks.append(ChunkPayload(
                chunk_id=chunk_id,
                content=content[:2000],
                week=week,
                category=category,
                topic=section.lower().replace(" ", "_") if section else "",
                priority=CATEGORY_PRIORITY[category],
                source_domain=SourceDomain.MIT_OCW_LECTURE,
                source_type="lecture_slide",
                page_number=page,
            ))

        return chunks


# ---------------------------------------------------------------------------
# Syllabus matrix (mirrors generate_dataset.py + setup_qdrant.py)
# ---------------------------------------------------------------------------
SYLLABUS_MATRIX: dict[int, dict[str, str]] = {
    1: {"name": "C Basics", "allowed": "printf, primitive types, main", "forbidden": "pointers, arrays, structures, new/delete"},
    2: {"name": "Arrays & Strings", "allowed": "arrays, string.h, functions", "forbidden": "pointers, dynamic allocation, structures"},
    3: {"name": "Pointers & Memory", "allowed": "raw pointers, references, stack allocation, address-of (&)", "forbidden": "new/delete, vectors, smart pointers"},
    4: {"name": "Manual Heap Management", "allowed": "new, delete, malloc, free, references", "forbidden": "std::vector, smart pointers, RAII objects"},
    5: {"name": "Object-Oriented C++", "allowed": "classes, inheritance, multiple inheritance, virtual functions, operator overload", "forbidden": "templates"},
    6: {"name": "Modern C++ & STL", "allowed": "std::vector, std::unique_ptr, RAII, templates, STL", "forbidden": "raw malloc/free, bare new/delete"},
    7: {"name": "Algorithms & Complexity", "allowed": "recursion, sorting algorithms, Big O notation, binary search trees", "forbidden": "raw malloc/free, bare new/delete"},
    8: {"name": "Advanced Data Structures", "allowed": "hash tables, tries, queues, stacks, linked lists", "forbidden": "raw malloc/free, bare new/delete"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_headers(text: str) -> str:
    """Remove TITLE/BREADCRUMB/SOURCE prefix lines from MIT OCW scraped text."""
    lines = text.split("\n")
    result: list[str] = []
    header_done = False
    for line in lines:
        if header_done:
            result.append(line)
        elif line.startswith("==="):
            header_done = True
    return "\n".join(result).strip()
