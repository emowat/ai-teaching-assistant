# Data Ingestion Pipeline

Scrapes, downloads, and extracts text from the MIT OCW 6.S096 (Introduction to C and C++) course materials.

## Directory Structure

### `raw_data/` — All ingested course content

```
raw_data/
│
├── mit_ocw_output/              # HTML page text (12 files)
│   ├── 00_index.txt             # Lectures and Assignments index page
│   ├── 01_compilation-pipeline.txt
│   ├── 02_core-c-control-structures-variables-scope-and-uninitialized-memory.txt
│   ├── 03_c-memory-management.txt
│   ├── 04_data-structures-debugging.txt
│   ├── 05_c-introduction-classes-and-templates.txt
│   ├── 06_c-inheritance.txt
│   ├── syllabus.txt             # Course syllabus, meeting times, software requirements
│   ├── final-project.txt        # Final project description + third-party library list
│   ├── starter-kit.txt          # Starter kit tutorial (libpng example)
│   ├── lines.c                  # Starter kit example C code (87 lines)
│   └── manifest.txt             # Crawl manifest listing all saved files
│
├── lecture_notes/               # Lecture slide PDFs (8 files)
│   ├── 01_lecture_1_compilation_pipeline.pdf          (1.0 MB, 120 slides)
│   ├── 02_lecture_2_core_c.pdf                        (115 KB, 26 slides)
│   ├── 03_lecture_3_c_memory_management.pdf           (392 KB, 43 slides)
│   ├── 04_lecture_4_data_structures_debugging.pdf     (346 KB, 39 slides)
│   ├── 05_lecture_5_c++_introduction_classes...pdf    (801 KB, 16 slides)
│   ├── 06_lecture_6_c++_inheritance.pdf               (584 KB, 60 slides)
│   ├── 07_lecture_7_parent_destructors...pdf           (444 KB, 51 slides)
│   └── 08_lecture_8_standard_template_library...pdf   (1.5 MB, 36 slides)
│
├── assignment_solutions/        # Assignment solution PDFs (2 files)
│   ├── assignment1_solution.pdf  (531 KB, 3 pages — Fibeverse C code)
│   └── assignment3_solution.pdf  (663 KB, 3 pages — Sort & Resize C code)
│
└── lecture_text/                # Extracted text (JSON + TXT, 20 files)
    ├── 01_lecture_1_compilation_pipeline.json    (120 slides, 71 with code)
    ├── 02_lecture_2_core_c.json                  (26 slides, 12 with code)
    ├── 03_lecture_3_c_memory_management.json     (43 slides, 33 with code)
    ├── 04_lecture_4_data_structures_debugging.json (39 slides, 26 with code)
    ├── 05_lecture_5_c++_introduction...json       (16 slides, 10 with code)
    ├── 06_lecture_6_c++_inheritance.json          (60 slides, 50 with code)
    ├── 07_lecture_7_parent_destructors...json     (51 slides, 37 with code)
    ├── 08_lecture_8_standard_template_library...json (36 slides, 32 with code)
    ├── assignment1_solution.json                 (3 pages, C code)
    ├── assignment3_solution.json                 (3 pages, C code)
    └── (matching .txt files for each .json)
```

### `data_ingestion/` — Scripts

| Script | Purpose |
|---|---|
| `mit_ocw_parser.py` | HTML scraper: parses course pages into plain text, crawls lecture sub-pages |
| `download_lecture_pdfs.py` | Discovers and downloads all lecture PDFs from the index page |
| `download_assignment_solutions.py` | Scans lecture sub-pages for solution PDF links and downloads them |
| `extract_pdf_text.py` | Extracts text from PDFs using pymupdf; outputs per-slide structured JSON + flat TXT |

## Data Summary

| Source | Format | Count | Details |
|---|---|---|---|
| Lecture slides | PDF → JSON/TXT | 8 | 391 total slides (271 with code) |
| HTML pages | TXT | 12 | Syllabus, lecture pages, final project, starter kit |
| Assignment solutions | PDF → JSON/TXT | 2 | Assignments 1 & 3 only (2/4/5/6 not published) |
| Starter code | C | 1 | `lines.c` (87 lines, libpng example) |

## JSON Slide Record Format

Each slide entry in `lecture_text/*.json`:

```json
{
  "page": 22,
  "section": "Today…",
  "text": "Pointers\nA pointer is a variable that...",
  "has_code": true
}
```

Assignment solutions use a simpler format: `{"page": 1, "text": "..."}`.

## Quick Start

```bash
# Scrape all course pages
python data_ingestion/mit_ocw_parser.py --url "<index-url>" --crawl --outdir raw_data/mit_ocw_output

# Download all lecture PDFs
python data_ingestion/download_lecture_pdfs.py --outdir raw_data/lecture_notes

# Download assignment solutions
python data_ingestion/download_assignment_solutions.py

# Extract text from PDFs
python data_ingestion/extract_pdf_text.py
```
