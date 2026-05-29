"""
PDF to structured text extractor for MIT OCW lecture slides.

Extracts each slide into a record with:
  - page_number
  - section_header (detected from "Today…" / "Summary" / title-like slides)
  - text (clean plain text)
  - has_code (heuristic: contains C/C++ keywords)

Outputs:
  - Per-lecture JSON: [{page_number, section, text, has_code}, ...]
  - Per-lecture TXT: flat text for quick inspection
"""
import json
import os
import re
import sys

import fitz  # pymupdf


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PDF_DIR = os.path.join(os.path.dirname(__file__), "lecture_notes")
OUT_DIR = os.path.join(os.path.dirname(__file__), "lecture_text")
os.makedirs(OUT_DIR, exist_ok=True)

# C/C++ keywords for code detection heuristic
CODE_KEYWORDS = {
    "int", "char", "float", "double", "void", "return", "if", "else",
    "for", "while", "do", "switch", "case", "break", "continue",
    "struct", "class", "public", "private", "virtual", "const",
    "static", "sizeof", "malloc", "free", "new", "delete",
    "printf", "scanf", "std::", "#include", "nullptr", "NULL",
    "strcpy", "strcat", "strlen",
}

# Section header detection patterns
SECTION_PATTERNS = [
    r"^Today[\u2026\\.]{1,3}\s*$",         # "Today…"
    r"^Summary\s*$",                         # "Summary"
    r"^Outline\s*$",
    r"^Agenda\s*$",
    r"^MIT OpenCourseWare\s*$",              # Final slide
    r"^\d+$",                                 # Just a page number
]


def _clean_text(text: str) -> str:
    """Remove excessive whitespace and unicode control chars."""
    # Remove form feed, vertical tab, and other control chars except newline/tab
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
    # Collapse multiple spaces
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse 3+ newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _has_code(text: str) -> bool:
    """Heuristic: check if text contains C/C++ code patterns."""
    tokens = set(re.findall(r"\b\w+\b", text.lower()))
    return bool(tokens & CODE_KEYWORDS) or "//" in text or "{" in text


def _is_section_header(line: str) -> bool:
    """Check if a line looks like a new section header slide."""
    for pattern in SECTION_PATTERNS:
        if re.match(pattern, line, re.IGNORECASE):
            return True
    return False


def extract_pdf(pdf_path: str) -> list[dict]:
    """
    Extract text from a PDF, organized per slide.

    Returns list of dicts:
        {"page": int, "section": str, "text": str, "has_code": bool}
    """
    doc = fitz.open(pdf_path)
    slides: list[dict] = []
    current_section = ""

    for page_num in range(doc.page_count):
        page = doc[page_num]
        raw = page.get_text()
        text = _clean_text(raw)

        if not text:
            continue

        lines = text.split("\n")
        first_line = lines[0].strip() if lines else ""

        # Detect section boundaries
        if _is_section_header(first_line):
            current_section = first_line

        slides.append({
            "page": page_num + 1,
            "section": current_section,
            "text": text,
            "has_code": _has_code(text),
        })

    doc.close()
    return slides


def slides_to_flat_text(slides: list[dict]) -> str:
    """Convert slides to a flat text block, one header per slide."""
    parts = []
    for s in slides:
        header = f"[Slide {s['page']}]"
        if s["section"]:
            header += f" ({s['section']})"
        parts.append(header)
        parts.append(s["text"])
        parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    pdf_files = sorted(
        f for f in os.listdir(PDF_DIR) if f.endswith(".pdf")
    )

    if not pdf_files:
        print(f"No PDFs found in {PDF_DIR}")
        sys.exit(1)

    print(f"Processing {len(pdf_files)} PDFs...\n")

    for pdf_name in pdf_files:
        pdf_path = os.path.join(PDF_DIR, pdf_name)
        base = os.path.splitext(pdf_name)[0]

        print(f"  {pdf_name}: ", end="", flush=True)
        slides = extract_pdf(pdf_path)

        # Save structured JSON
        json_path = os.path.join(OUT_DIR, f"{base}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(slides, f, ensure_ascii=False, indent=2)

        # Save flat text for quick reading
        txt_path = os.path.join(OUT_DIR, f"{base}.txt")
        flat = slides_to_flat_text(slides)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(flat)

        code_slides = sum(1 for s in slides if s["has_code"])
        print(f"{len(slides)} slides ({code_slides} with code) -> {json_path}")

    # Summary
    json_files = [f for f in os.listdir(OUT_DIR) if f.endswith(".json")]
    total_slides = 0
    for jf in json_files:
        with open(os.path.join(OUT_DIR, jf)) as f:
            total_slides += len(json.load(f))

    print(f"\nDone. {total_slides} total slides across {len(json_files)} lectures.")
    print(f"Output: {OUT_DIR}/")


if __name__ == "__main__":
    main()
