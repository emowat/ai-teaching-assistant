"""Deterministic mapping from chunk provenance to a real, browsable source URL.

The retrieval payloads store provenance as S3 URIs and file names (e.g.
``MIT6_S096IAP14_Lecture10.pdf``), never a public web link. The TA prompt, however,
asks the model to append a ``[1](URL)`` citation. Without a real URL in context the
model hallucinates one — historically a 404 OCW link using the wrong course slug and a
non-existent ``/resources/.../index.html`` path, or a bare ``[reference here]``
placeholder. This module turns the stored provenance into a verified, existing URL so
the model can cite a real page instead of inventing one.

The URLs point at the OCW *section* pages (lecture notes / assignments / syllabus),
which are stable and guaranteed to exist, rather than guessing per-file resource slugs.
"""
from __future__ import annotations

from rag.schemas import SourceDomain

_OCW_BASE = "https://ocw.mit.edu/courses"

# Canonical OCW course slugs (verified to exist). The 2014 course was renamed
# "Effective Programming in C and C++"; 2013 is "Introduction to C and C++".
_OCW_COURSE_SLUGS = {
    "mit13": "6-s096-introduction-to-c-and-c-january-iap-2013",
    "mit14": "6-s096-effective-programming-in-c-and-c-january-iap-2014",
}

# Stable landing pages for the non-OCW knowledge sources.
_STATIC_DOMAIN_URLS = {
    SourceDomain.CPP_CORE_GUIDELINES: "https://isocpp.github.io/CppCoreGuidelines/CppCoreGuidelines",
    SourceDomain.CPP_REFERENCE: "https://en.cppreference.com/w/",
    SourceDomain.HARVARD_CS50: "https://cs50.harvard.edu/x/",
}


def _canonical_course(course_id: str) -> str | None:
    """Collapse the many course_id spellings (``mit_2014``, ``mit14``, ...) to a key."""
    c = "".join(ch for ch in (course_id or "").casefold() if ch.isalnum())
    if not c:
        return None
    if "cs50" in c or "harvard" in c:
        return "cs50"
    if "2013" in c or c == "mit13":
        return "mit13"
    if "2014" in c or c == "mit14":
        return "mit14"
    return None


def _ocw_section(*, source_domain: SourceDomain, file_name: str) -> str:
    """Pick the OCW page (syllabus / assignments / lecture-notes) for a chunk."""
    name = (file_name or "").casefold()
    is_assignment = "_ass" in name or "assignment" in name
    if source_domain is SourceDomain.MIT_OCW_SYLLABUS or "syllabus" in name:
        return "pages/syllabus/"
    if source_domain is SourceDomain.MIT_OCW_ASSIGNMENT or is_assignment:
        return "pages/assignments/"
    if source_domain is SourceDomain.MIT_OCW_LECTURE or "lecture" in name:
        return "pages/lecture-notes/"
    # Unknown MIT material: link to the course landing page (still valid).
    return ""


def build_source_url(
    *,
    source_domain: SourceDomain,
    course_id: str = "",
    file_name: str = "",
) -> str:
    """Return a real, existing URL for a retrieved chunk, or "" if none is known.

    Returning "" (rather than a guess) is deliberate: the prompt instructs the model to
    cite only when a Source URL is supplied, so an empty result means "no citation" — never
    a fabricated link.
    """
    static = _STATIC_DOMAIN_URLS.get(source_domain)
    if static is not None:
        return static

    slug = None
    canonical = _canonical_course(course_id)
    if canonical in _OCW_COURSE_SLUGS:
        slug = _OCW_COURSE_SLUGS[canonical]
    elif source_domain in (
        SourceDomain.MIT_OCW_LECTURE,
        SourceDomain.MIT_OCW_ASSIGNMENT,
        SourceDomain.MIT_OCW_SYLLABUS,
    ):
        # MIT material with an unrecognized course_id — default to the 2014 course.
        slug = _OCW_COURSE_SLUGS["mit14"]

    if slug is None:
        return ""

    section = _ocw_section(source_domain=source_domain, file_name=file_name)
    return f"{_OCW_BASE}/{slug}/{section}"
