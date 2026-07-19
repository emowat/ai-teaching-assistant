"""
Minimal Pydantic schemas for the RAG pipeline.
Covers: Qdrant document payload, retrieval query input, retrieval result output.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DocCategory(str, Enum):
    """Document categories mirroring generate_dataset.py's RAG_DOCUMENT_BANK."""
    SYLLABUS = "Syllabus"
    STRICT_RULES = "Strict_Rules"
    PEDAGOGICAL_CONTEXT = "Pedagogical_Context"
    SUPPLEMENTARY = "Supplementary"
    GUIDELINE = "Guideline"


class SourceDomain(str, Enum):
    """Allowed knowledge sources for retrieval scoping."""
    MIT_OCW_LECTURE = "mit_ocw_lecture"
    MIT_OCW_SYLLABUS = "mit_ocw_syllabus"
    MIT_OCW_ASSIGNMENT = "mit_ocw_assignment"
    CPP_CORE_GUIDELINES = "cpp_core_guidelines"
    CPP_REFERENCE = "cpp_reference"
    HARVARD_CS50 = "harvard_cs50"


class CourseSource(str, Enum):
    """Which course the student is enrolled in — drives collection selection."""
    MIT_13 = "mit13"
    MIT_14 = "mit14"
    CS50 = "cs50"


class AssistMode(str, Enum):
    HOMEWORK_ASSIST = "Homework Assist"
    STUDY_ASSIST = "Study Assist"


# ---------------------------------------------------------------------------
# Qdrant payload (what gets indexed)
# ---------------------------------------------------------------------------

class ChunkPayload(BaseModel):
    """A single document chunk stored in Qdrant."""
    chunk_id: str
    content: str

    week: int = Field(ge=0, le=8, description="Course week 1-8, or 0 for week-agnostic reference")
    category: DocCategory
    topic: str = ""                       # e.g. "pointer_arithmetic"
    priority: int = Field(default=2, ge=1, le=3, description="1=highest (Syllabus/Rules), 2=Pedagogical, 3=Supplementary")

    # For parent-child chunk linking (expanding a small rule into its section)
    parent_chunk_id: Optional[str] = None

    # Source provenance
    source_domain: SourceDomain = SourceDomain.MIT_OCW_LECTURE
    source_type: str = ""                 # "lecture_slide", "assignment_solution", "syllabus_page"
    page_number: Optional[int] = None


# ---------------------------------------------------------------------------
# Retrieval request
# ---------------------------------------------------------------------------

class ASTFeatures(BaseModel):
    """Subset of AST metadata relevant for query expansion."""
    has_pointer: bool = False
    has_reference: bool = False
    has_loop: bool = False
    has_new: bool = False
    has_delete: bool = False
    has_malloc: bool = False
    has_free: bool = False
    has_recursion: bool = False
    has_stl_algorithm: bool = False
    has_smart_pointer: bool = False
    has_iterator: bool = False
    target_variables: list[str] = Field(default_factory=list)
    near_cursor_stl: list[str] = Field(default_factory=list)


class ClipboardEvent(BaseModel):
    external_paste_detected: bool = False
    pasted_char_count: int = 0


class EngagementMetrics(BaseModel):
    active_editor_seconds: int = 0
    active_shell_seconds: int = 0
    active_chat_seconds: int = 0
    rewards_given: int = 0
    style_nudges: int = 0


class QueryInput(BaseModel):
    """What the TA orchestration layer sends to the retrieval endpoint."""
    student_message: str
    # Optional standalone query for retrieval. The backend fills this for
    # follow-up turns (e.g. "How about now") whose current message carries no
    # standalone signal; retrieval embeds it instead of student_message.
    # Generation is unaffected — it consumes the full message history natively.
    retrieval_query: str | None = None
    code_raw: str = ""                    # raw C++ code in editor (with line numbers ok)
    terminal_output: str = ""
    exit_code: int = 0
    week: int = Field(ge=0, le=8)
    mode: AssistMode = AssistMode.HOMEWORK_ASSIST
    ast_features: ASTFeatures = Field(default_factory=ASTFeatures)
    clipboard_event: Optional[ClipboardEvent] = None
    engagement_metrics: Optional[EngagementMetrics] = None
    course_id: Optional[str] = None
    course_source: CourseSource = CourseSource.MIT_14
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    turn_id: Optional[str] = None
    section_id: Optional[str] = None
    syllabus_matrix: Optional[str] = None
    style_guide: Optional[str] = None


# ---------------------------------------------------------------------------
# Retrieval response
# ---------------------------------------------------------------------------

class RetrievedDoc(BaseModel):
    """A single retrieved document returned to the caller."""
    chunk_id: str
    content: str
    category: DocCategory
    week: int
    priority: int
    score: float = 0.0                    # similarity or reranker score
    source_domain: SourceDomain = SourceDomain.MIT_OCW_LECTURE
    source_type: str = ""
    file_name: str = ""                   # original document, e.g. "MIT6_S096IAP14_Lecture10.pdf"
    source_url: str = ""                  # real, browsable citation URL (empty if none known)


class RetrievalResult(BaseModel):
    """Complete retrieval response."""
    syllabus: Optional[RetrievedDoc] = None     # guaranteed one, may be None on retrieval failure
    strict_rules: list[RetrievedDoc] = Field(default_factory=list)
    pedagogical: list[RetrievedDoc] = Field(default_factory=list)
    supplementary: list[RetrievedDoc] = Field(default_factory=list)
    guidelines: list[RetrievedDoc] = Field(default_factory=list)
    harvard: list[RetrievedDoc] = Field(default_factory=list)
    query_string: str = ""        # course content query (student NL question)
    cpp_query_string: str = ""     # CPP reference query (AST keyword hints)


    # Pre-formatted context block ready for TA prompt injection
    formatted_context: str = ""
