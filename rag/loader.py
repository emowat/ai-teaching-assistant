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
    DocCategory.GUIDELINE: 2,
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

MIT_2014_MATRIX: dict[int, dict[str, str]] = {
    1: {"name": "Introduction to C: Welcome to the Memory Jungle", "allowed": "primitive types, control loops, functions, basic pointers, sizeof, printf", "forbidden": "structs, custom alignment, manual malloc, assembly, C++ classes"},
    2: {"name": "Subtleties of C: Data Structures & Floating-Point", "allowed": "structures, raw pointers, custom memory alignment, custom trees/lists, floating-point arithmetic", "forbidden": "x86 assembly, pointer casting exploits, C++ references, new/delete"},
    3: {"name": "Assembly & Secure Programming in C", "allowed": "x86 assembly registers, stack frames, buffer overflow analysis, bounds checking", "forbidden": "C++ syntax, classes, std::vector, iostream"},
    4: {"name": "Style and Structure: Transition from C to C++", "allowed": "namespaces, function overloading, standard reference variables (&), iostream (std::cout), stack-allocated custom vectors", "forbidden": "C++ classes, inheritance, explicit heap management (new/delete)"},
    5: {"name": "Object-Oriented C++: Abstraction & Core STL", "allowed": "classes, access modifiers (public/private), basic inheritance, std::vector, std::queue", "forbidden": "templates, raw pointer dynamic casting, complex pointers, manual memory deletion"},
    6: {"name": "Design Patterns: Higher-Level Program Design", "allowed": "virtual functions, polymorphism, abstract base classes, composite pattern, strategy pattern, std::unique_ptr", "forbidden": "raw malloc/free, third-party frameworks, manual pointer arithmetic inside patterns"},
    7: {"name": "Introduction to Projects: Unit Testing & Review", "allowed": "assert, unit test blocks, third-party header libraries, modular compilation", "forbidden": "makefiles, large-scale multi-directory linkages, graphical engines"},
    8: {"name": "Project Environments: Iterators & N-Body Setup", "allowed": "STL iterators, macro definitions (#define), header guards, math.h, simulation loops", "forbidden": "raw pointer traversal (must use iterators), OpenGL, automated graphics libraries"},
    9: {"name": "Visualization & Build Systems", "allowed": "GNU Makefiles, compiler optimization flags (-O2, -O3), basic OpenGL context, structural linking", "forbidden": "unoptimized code paths, nested raw loops without look-ahead analysis"},
    10: {"name": "Course Recap, Technical Interviews, & Advanced Topics", "allowed": "rvalue references, move semantics, template metaprogramming concepts, interview data structures", "forbidden": "legacy C practices (e.g., raw void* pointers where type-safety applies)"},
}

CS50_SYLLABUS_MATRIX: dict[int, dict[str, str]] = {
    1: {"name": "C Basics", "allowed": "C primitives, loops, conditionals, variables, operators, cs50.h (get_int, get_string), stdio.h (printf)", "forbidden": "arrays, pointers, structs, dynamic memory (malloc/free), C++ features (std::cout, classes)"},
    2: {"name": "Arrays & Strings", "allowed": "arrays, strings, command-line arguments (argc, argv), string.h functions, ctype.h", "forbidden": "pointers, dynamic memory (malloc/free), structs, file I/O"},
    3: {"name": "Algorithms", "allowed": "recursion, sorting algorithms (bubble, selection, merge), linear/binary search", "forbidden": "pointers, dynamic memory (malloc/free), structs, file I/O"},
    4: {"name": "Memory & File I/O", "allowed": "pointers, dynamic memory allocation (malloc, free, realloc), stack/heap manipulation, file I/O (fopen, fread, fwrite)", "forbidden": "abstract data types (linked lists, trees, hash tables), C++ features (new/delete, std::fstream)"},
    5: {"name": "Data Structures", "allowed": "structs, linked lists, trees, binary search trees, hash tables, tries", "forbidden": "C++ STL containers (std::vector, std::map), classes, smart pointers"},
}


# ---------------------------------------------------------------------------
# C++ Core Guidelines loader
# ---------------------------------------------------------------------------

GUIDELINES_JSON_PATH = Path("cppcoreguidelines") / "cppcoreguidelines.json"


class CppGuidelinesLoader:
    """Loads C++ Core Guidelines from raw_data/cppcoreguidelines/cppcoreguidelines.json.

    Chunking strategy (2 chunk types):
      - ``rule``:      rule_number + title + reason (compact reference, ~80-200 tokens)
      - ``rule_example``: rule_number + title + code example (~100-400 tokens)
      These are indexed as separate chunks for fine-grained retrieval; a query
      matching a specific code pattern hits an example chunk directly rather
      than retrieving the entire rule.

    Usage:
        loader = CppGuidelinesLoader("raw_data")
        chunks = loader.load_all()
    """

    MAX_CONTENT_LENGTH = 2000

    def __init__(self, raw_data_path: str | Path):
        self.raw_data = Path(raw_data_path)
        self.json_path = self.raw_data / GUIDELINES_JSON_PATH
        if not self.json_path.exists():
            raise FileNotFoundError(f"Guidelines JSON not found: {self.json_path}")

    def load_all(self) -> list[ChunkPayload]:
        """Parse the guidelines JSON and return two chunk types per h3 rule."""
        data = json.loads(self.json_path.read_text(encoding="utf-8"))
        chunks: list[ChunkPayload] = []
        rule_count = 0
        example_count = 0

        for entry in data:
            if entry.get("level") != 3:
                continue

            title = str(entry.get("title", ""))
            rule_number = str(entry.get("rule_number", ""))
            section = str(entry.get("section", ""))
            reason = str(entry.get("reason", ""))
            examples = entry.get("examples", [])

            base_topic = f"cpp_guideline::{rule_number}" if rule_number else "cpp_guideline"

            # --- chunk type: rule (summary) ---
            parts: list[str] = []
            if section:
                parts.append(f"[{section}]")
            parts.append(f"Rule {rule_number}: {title}" if rule_number else f"Rule: {title}")
            if reason:
                parts.append(f"Reason: {reason}")

            content = "\n".join(parts)
            if len(content) > self.MAX_CONTENT_LENGTH:
                content = content[: self.MAX_CONTENT_LENGTH]

            if content.strip():
                rule_id = _stable_chunk_id("cpp_guideline", "rule", rule_number or title)
                chunks.append(ChunkPayload(
                    chunk_id=rule_id,
                    content=content,
                    week=0,
                    category=DocCategory.GUIDELINE,
                    topic=base_topic,
                    priority=CATEGORY_PRIORITY.get(DocCategory.GUIDELINE, 2),
                    source_domain=SourceDomain.CPP_CORE_GUIDELINES,
                    source_type="cpp_core_guideline_rule",
                ))
                rule_count += 1

            # --- chunk type: rule_example (code examples) ---
            for i, ex in enumerate(examples):
                code = str(ex.get("code", "")).strip()
                if not code:
                    continue
                label = str(ex.get("label", f"Example {i + 1}"))
                desc = str(ex.get("description", "")).strip()

                example_content = f"[{section}] Rule {rule_number}: {title}\n{label}: {desc}\n```cpp\n{code}\n```"
                if len(example_content) > self.MAX_CONTENT_LENGTH:
                    example_content = example_content[: self.MAX_CONTENT_LENGTH]

                example_id = _stable_chunk_id("cpp_guideline", "example", rule_number or title, str(i))
                chunks.append(ChunkPayload(
                    chunk_id=example_id,
                    content=example_content,
                    week=0,
                    category=DocCategory.GUIDELINE,
                    topic=f"{base_topic}::example",
                    priority=CATEGORY_PRIORITY.get(DocCategory.GUIDELINE, 2),
                    source_domain=SourceDomain.CPP_CORE_GUIDELINES,
                    source_type="cpp_core_guideline_example",
                    parent_chunk_id=rule_id,
                ))
                example_count += 1

        print(f"  cppcoreguidelines.json: {rule_count} rules + {example_count} examples = {rule_count + example_count} chunks")
        return chunks


# ---------------------------------------------------------------------------
# C++ Reference (cppreference.com) loader
# ---------------------------------------------------------------------------

CPPREFERENCE_JSON_PATH = Path("cppreference") / "cppreference.json"


class CppReferenceLoader:
    """Loads the cppreference HTML book parse output and produces granular chunks.

    Chunking strategy (4 chunk types per API entry):

      ``summary``
        name + header + declarations + description
        ~150-400 tokens.  Answers *"what is std::vector?"* queries.

      ``section``
        name + section_name + section_content  (one per section: Parameters,
        Return value, Complexity, Exceptions, Notes, Example, See also...)
        ~80-300 tokens.  Answers *"what is the complexity of std::find?"*.

      ``example``
        name + code example  (only when example text is non-empty)
        ~100-500 tokens.  Answers *"show me an example of std::sort"*.

      ``member``
        parent_name + member_name + member_description
        ~50-150 tokens.  Answers *"what does vector::push_back do?"*.

    Usage:
        loader = CppReferenceLoader("raw_data")
        chunks = loader.load_all()
    """

    MAX_CONTENT_LENGTH = 3000

    def __init__(self, raw_data_path: str | Path):
        self.raw_data = Path(raw_data_path)
        self.json_path = self.raw_data / CPPREFERENCE_JSON_PATH
        if not self.json_path.exists():
            raise FileNotFoundError(f"CppReference JSON not found: {self.json_path}")

    def load_all(self) -> list[ChunkPayload]:
        """Parse the cppreference JSON and return 4 chunk types per entry."""
        data = json.loads(self.json_path.read_text(encoding="utf-8"))
        chunks: list[ChunkPayload] = []
        counts = {"summary": 0, "section": 0, "example": 0, "member": 0}

        for entry in data:
            name = str(entry.get("name", ""))
            path = str(entry.get("path", ""))
            category = str(entry.get("category", ""))
            header = str(entry.get("header", ""))
            declarations = entry.get("declarations", [])
            description = str(entry.get("description", ""))
            sections = entry.get("sections", {})
            example = str(entry.get("example", ""))
            members = entry.get("members", [])

            base_topic = f"cppref::{category}::{path}" if category else f"cppref::{path}"

            # --- chunk type: summary ---
            summary_parts: list[str] = [f"`{name}`"]
            if header:
                summary_parts.append(f"Header: {header}")
            if declarations:
                summary_parts.append("Declarations:")
                for d in declarations[:6]:  # cap to 6 to limit token count
                    summary_parts.append(f"  {d}")
            if description:
                summary_parts.append(description)

            summary_text = "\n".join(summary_parts)
            if len(summary_text) > self.MAX_CONTENT_LENGTH:
                summary_text = summary_text[: self.MAX_CONTENT_LENGTH]

            if summary_text.strip():
                summary_id = _stable_chunk_id("cppref", "summary", path, name)
                chunks.append(ChunkPayload(
                    chunk_id=summary_id,
                    content=summary_text,
                    week=0,
                    category=DocCategory.GUIDELINE,
                    topic=base_topic,
                    priority=CATEGORY_PRIORITY.get(DocCategory.GUIDELINE, 2),
                    source_domain=SourceDomain.CPP_REFERENCE,
                    source_type="cppref_summary",
                ))
                counts["summary"] += 1

            # --- chunk type: section (one per section) ---
            for section_name, section_text in sections.items():
                if not section_text.strip():
                    continue
                section_content = f"`{name}` — {section_name}\n{section_text}"
                if len(section_content) > self.MAX_CONTENT_LENGTH:
                    section_content = section_content[: self.MAX_CONTENT_LENGTH]

                section_id = _stable_chunk_id("cppref", "section", path, name, section_name)
                chunks.append(ChunkPayload(
                    chunk_id=section_id,
                    content=section_content,
                    week=0,
                    category=DocCategory.GUIDELINE,
                    topic=f"{base_topic}::{section_name.lower().replace(' ', '_')[:40]}",
                    priority=CATEGORY_PRIORITY.get(DocCategory.GUIDELINE, 2),
                    source_domain=SourceDomain.CPP_REFERENCE,
                    source_type="cppref_section",
                    parent_chunk_id=summary_id,
                ))
                counts["section"] += 1

            # --- chunk type: example ---
            if example.strip():
                example_content = f"`{name}` example:\n```cpp\n{example}\n```"
                if len(example_content) > self.MAX_CONTENT_LENGTH:
                    example_content = example_content[: self.MAX_CONTENT_LENGTH]

                example_id = _stable_chunk_id("cppref", "example", path, name)
                chunks.append(ChunkPayload(
                    chunk_id=example_id,
                    content=example_content,
                    week=0,
                    category=DocCategory.GUIDELINE,
                    topic=f"{base_topic}::example",
                    priority=CATEGORY_PRIORITY.get(DocCategory.GUIDELINE, 2),
                    source_domain=SourceDomain.CPP_REFERENCE,
                    source_type="cppref_example",
                    parent_chunk_id=summary_id,
                ))
                counts["example"] += 1

            # --- chunk type: member (one per member function/type) ---
            for m in members:
                member_name = str(m.get("name", "")).strip()
                member_desc = str(m.get("description", "")).strip()
                if not member_name:
                    continue

                member_content = f"`{name}::{member_name}`"
                if member_desc:
                    member_content += f"\n{member_desc}"
                if len(member_content) > self.MAX_CONTENT_LENGTH:
                    member_content = member_content[: self.MAX_CONTENT_LENGTH]

                member_id = _stable_chunk_id("cppref", "member", path, name, member_name)
                chunks.append(ChunkPayload(
                    chunk_id=member_id,
                    content=member_content,
                    week=0,
                    category=DocCategory.GUIDELINE,
                    topic=f"{base_topic}::member::{member_name.lower().replace(' ', '_')[:50]}",
                    priority=CATEGORY_PRIORITY.get(DocCategory.GUIDELINE, 2),
                    source_domain=SourceDomain.CPP_REFERENCE,
                    source_type="cppref_member",
                    parent_chunk_id=summary_id,
                ))
                counts["member"] += 1

        total = sum(counts.values())
        print(f"  cppreference.json: {counts['summary']} summary + {counts['section']} section "
              f"+ {counts['example']} example + {counts['member']} member = {total} chunks")
        return chunks


# ---------------------------------------------------------------------------
# MIT 2014 loader (parsed PDF blocks)
# ---------------------------------------------------------------------------

MIT14_JSON_DIR = Path("MIT_2014")

# Lecture filename → week
_MIT14_LECTURE_WEEK: dict[str, int] = {
    "Lecture1": 1,
    "Lecture2": 2,
    "Lecture3A": 3,
    "Lecture3S": 3,
    "Lecture4": 4,
    "Lecture5": 5,
    "Lecture6": 6,
    "Lecture7": 7,
    "Lecture8": 8,
    "Lecture9": 8,
    "Lecture10": 8,
}

# Assignment filename prefix → approximate week
_MIT14_ASSIGNMENT_WEEK: dict[str, int] = {
    "ass1": 2,
    "ass2": 4,
    "ass3": 6,
}


class MIT14Loader:
    """Loads MIT 2014 parsed PDF/TXT files from raw_data/MIT_2014/.

    Chunking strategy:
      - **Lecture slides**: one chunk per block (= one page/slide). ~50-500 chars.
        Category: Pedagogical_Context (default) or Strict_Rules (imperative keywords).
      - **Syllabus**: one chunk from the full syllabus text.
        Category: Syllabus.
      - **Assignments**: one chunk per block. Category: Supplementary.

    Usage:
        loader = MIT14Loader("raw_data")
        chunks = loader.load_all()
    """

    MAX_CONTENT_LENGTH = 2000

    def __init__(self, raw_data_path: str | Path):
        self.raw_data = Path(raw_data_path)
        self.mit_dir = self.raw_data / MIT14_JSON_DIR
        if not self.mit_dir.exists():
            raise FileNotFoundError(f"MIT 2014 directory not found: {self.mit_dir}")

    def load_all(self) -> list[ChunkPayload]:
        """Parse all MIT14 JSON files and return one chunk per block."""
        chunks: list[ChunkPayload] = []
        lecture_count = 0
        assignment_count = 0

        for json_file in sorted(self.mit_dir.glob("*__pdf.json")):
            data = json.loads(json_file.read_text(encoding="utf-8"))
            file_name = str(data.get("file_name", json_file.stem))
            blocks = data.get("blocks", [])

            week, source_type = self._classify_file(file_name)

            for block in blocks:
                text = str(block.get("text", "")).strip()
                if not text:
                    continue

                page = block.get("page_number")
                has_code = bool(block.get("has_code", False))

                # Category: same heuristic as CourseMaterialLoader
                category = classify_category(text, has_code, source=(
                    "assignment_solution" if "ass" in file_name.lower() else "lecture"
                ))

                # Prefix with source context
                source_label = file_name.replace("MIT6_S096IAP14_", "").replace("__pdf", "")
                content = f"[{source_label} p.{page}] {text}"
                if len(content) > self.MAX_CONTENT_LENGTH:
                    content = content[: self.MAX_CONTENT_LENGTH]

                chunk_id = _stable_chunk_id(
                    "mit14",
                    file_name,
                    block.get("block_id", str(page)),
                    text[:500],
                )

                chunks.append(ChunkPayload(
                    chunk_id=chunk_id,
                    content=content,
                    week=week,
                    category=category,
                    topic=f"mit14::{source_label.lower()}",
                    priority=CATEGORY_PRIORITY.get(category, 2),
                    source_domain=SourceDomain.MIT_OCW_LECTURE,
                    source_type=source_type,
                    page_number=page,
                ))

                if "ass" in file_name.lower():
                    assignment_count += 1
                else:
                    lecture_count += 1

        # --- Syllabus ---
        syllabus_chunks = self._load_syllabus()
        chunks.extend(syllabus_chunks)

        print(f"  MIT 2014: {lecture_count} lecture + {assignment_count} assignment "
              f"+ {len(syllabus_chunks)} syllabus = {len(chunks)} chunks")
        return chunks

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _classify_file(self, file_name: str) -> tuple[int, str]:
        """Return (week, source_type) from the file name."""
        # Try lecture mapping (longest key first to avoid "Lecture1" matching "Lecture10")
        for key in sorted(_MIT14_LECTURE_WEEK, key=len, reverse=True):
            if key in file_name:
                return _MIT14_LECTURE_WEEK[key], "lecture_slide"

        # Try assignment mapping (same logic)
        for key in sorted(_MIT14_ASSIGNMENT_WEEK, key=len, reverse=True):
            if key in file_name:
                return _MIT14_ASSIGNMENT_WEEK[key], "assignment_solution"

        return 0, "lecture_slide"

    def _load_syllabus(self) -> list[ChunkPayload]:
        """Build syllabus chunks from MIT_2014_MATRIX with optional file description."""
        chunks: list[ChunkPayload] = []

        # Try loading supplementary description from file
        description = ""
        json_path = self.mit_dir / "syllabus__txt.json"
        txt_path = self.mit_dir / "syllabus.txt"
        if json_path.exists():
            data = json.loads(json_path.read_text(encoding="utf-8"))
            blocks = data.get("blocks", [])
            if blocks:
                description = blocks[0].get("text", "")[:500]
        elif txt_path.exists():
            description = txt_path.read_text(encoding="utf-8")[:500]

        for week, info in MIT_2014_MATRIX.items():
            chunk_id = _stable_chunk_id("mit14", "syllabus", str(week), info["name"])
            content = (
                f"Week: {week} - {info['name']}\n"
                f"Allowed: {info['allowed']}\n"
                f"Forbidden: {info['forbidden']}"
            )
            if description:
                content += f"\n\n{description}"
            chunks.append(ChunkPayload(
                chunk_id=chunk_id,
                content=content,
                week=week,
                category=DocCategory.SYLLABUS,
                topic="mit14_syllabus",
                priority=1,
                source_domain=SourceDomain.MIT_OCW_SYLLABUS,
                source_type="syllabus_page",
            ))

        return chunks


# ---------------------------------------------------------------------------
# Harvard CS50 Notes loader
# ---------------------------------------------------------------------------

HARVARD_NOTES_JSON_DIR = Path("Harvard") / "cs50_output" / "notes_json"


class HarvardNotesLoader:
    """Loads Harvard CS50 lecture notes from raw_data/Harvard/cs50_output/notes_json/*.json.

    Chunking strategy:
      - One chunk per section (heading + text block).
      - Uses the same category classification heuristic as MIT materials.
      - Weeks 0-5 map directly to the CS50 curriculum.

    Usage:
        loader = HarvardNotesLoader("raw_data")
        chunks = loader.load_all()
    """

    MAX_CONTENT_LENGTH = 4000

    def __init__(self, raw_data_path: str | Path):
        self.raw_data = Path(raw_data_path)
        self.notes_dir = self.raw_data / HARVARD_NOTES_JSON_DIR
        if not self.notes_dir.exists():
            raise FileNotFoundError(f"Harvard notes directory not found: {self.notes_dir}")

    def load_all(self) -> list[ChunkPayload]:
        """Parse all notes_N.json files and return one chunk per section."""
        chunks: list[ChunkPayload] = []
        json_files = sorted(self.notes_dir.glob("notes_*.json"))

        for json_file in json_files:
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                print(f"  WARNING: could not parse {json_file.name}")
                continue

            week = int(data.get("week", 0))
            title = str(data.get("title", ""))
            sections = data.get("sections", [])

            file_chunks: list[ChunkPayload] = []
            for section in sections:
                heading = str(section.get("heading", "")).strip()
                text = str(section.get("text", "")).strip()
                has_code = bool(section.get("has_code", False))

                if not text:
                    continue

                # Assemble structured content with heading context
                content = f"[{heading}] {text}" if heading else text
                if len(content) > self.MAX_CONTENT_LENGTH:
                    content = content[: self.MAX_CONTENT_LENGTH]

                category = classify_category(text, has_code, source="lecture")
                topic = heading.lower().replace(" ", "_") if heading else ""

                chunk_id = _stable_chunk_id(
                    "harvard_cs50_note",
                    json_file.name,
                    heading,
                    text[:500],
                )

                file_chunks.append(ChunkPayload(
                    chunk_id=chunk_id,
                    content=content,
                    week=week,
                    category=category,
                    topic=topic,
                    priority=CATEGORY_PRIORITY.get(category, 2),
                    source_domain=SourceDomain.HARVARD_CS50,
                    source_type="harvard_cs50_note",
                    page_number=None,
                ))

            chunks.extend(file_chunks)
            print(f"  {json_file.name}: week={week} ({title}), {len(file_chunks)} sections")

        # Syllabus
        syllabus_chunks = self._load_syllabus()
        chunks.extend(syllabus_chunks)

        print(f"Harvard CS50: {len(chunks)} total chunks indexed")
        return chunks

    def _load_syllabus(self) -> list[ChunkPayload]:
        """Build syllabus chunks from CS50_SYLLABUS_MATRIX (weeks 1-5)."""
        chunks: list[ChunkPayload] = []
        for week, info in CS50_SYLLABUS_MATRIX.items():
            chunk_id = _stable_chunk_id("cs50", "syllabus", str(week), info["name"])
            content = (
                f"Week: {week} - {info['name']}\n"
                f"Allowed: {info['allowed']}\n"
                f"Forbidden: {info['forbidden']}"
            )
            chunks.append(ChunkPayload(
                chunk_id=chunk_id,
                content=content,
                week=week,
                category=DocCategory.SYLLABUS,
                topic="cs50_syllabus",
                priority=1,
                source_domain=SourceDomain.HARVARD_CS50,
                source_type="syllabus_page",
            ))
        return chunks


# ---------------------------------------------------------------------------
# Harvard CS50 Transcripts loader
# ---------------------------------------------------------------------------

HARVARD_TRANSCRIPTS_DIR = Path("Harvard") / "cs50_transcripts"


class HarvardTranscriptsLoader:
    """Loads Harvard CS50 lecture transcripts from raw_data/Harvard/cs50_transcripts/*.json.

    Chunking strategy:
      - One chunk per paragraph (natural speech boundary).
      - Paragraphs shorter than MIN_CHAR_LENGTH are skipped (likely noise).
      - Category: Pedagogical_Context (spoken lecture content).
      - Weeks 1-5 map to the CS50 curriculum.

    Usage:
        loader = HarvardTranscriptsLoader("raw_data")
        chunks = loader.load_all()
    """

    MAX_CONTENT_LENGTH = 3000
    MIN_CHAR_LENGTH = 50

    def __init__(self, raw_data_path: str | Path):
        self.raw_data = Path(raw_data_path)
        self.transcripts_dir = self.raw_data / HARVARD_TRANSCRIPTS_DIR
        if not self.transcripts_dir.exists():
            raise FileNotFoundError(f"Transcripts directory not found: {self.transcripts_dir}")

    def load_all(self) -> list[ChunkPayload]:
        """Parse all lecture*.json files and return one chunk per paragraph."""
        chunks: list[ChunkPayload] = []
        json_files = sorted(self.transcripts_dir.glob("lecture*.json"))

        for json_file in json_files:
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                print(f"  WARNING: could not parse {json_file.name}")
                continue

            week = int(data.get("week", 0))
            title = str(data.get("title", ""))
            paragraphs = data.get("paragraphs", [])

            file_chunks: list[ChunkPayload] = []
            for para in paragraphs:
                text = str(para.get("text", "")).strip()
                idx = para.get("index", 0)

                if len(text) < self.MIN_CHAR_LENGTH:
                    continue

                content = text
                if len(content) > self.MAX_CONTENT_LENGTH:
                    content = content[: self.MAX_CONTENT_LENGTH]

                # Transcripts are always Pedagogical_Context
                category = DocCategory.PEDAGOGICAL_CONTEXT

                chunk_id = _stable_chunk_id(
                    "harvard_cs50_transcript",
                    json_file.name,
                    str(idx),
                    text[:500],
                )

                file_chunks.append(ChunkPayload(
                    chunk_id=chunk_id,
                    content=content,
                    week=week,
                    category=category,
                    topic=f"transcript::{title}",
                    priority=CATEGORY_PRIORITY.get(category, 2),
                    source_domain=SourceDomain.HARVARD_CS50,
                    source_type="harvard_cs50_transcript",
                    page_number=None,
                ))

            chunks.extend(file_chunks)
            print(f"  {json_file.name}: week={week} ({title}), {len(file_chunks)} paragraphs")

        print(f"Harvard Transcripts: {len(chunks)} total chunks indexed")
        return chunks


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
