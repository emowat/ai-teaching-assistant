# Synthetic C++ Dataset Statistics

## Dataset Distribution

| Metric | Evaluation Set | Training Set |
| :--- | :--- | :--- |
| **Total Transcripts** | 101 | 1049 |
| **Homework Assist** | 81 (80.2%) | 897 (85.5%) |
| **Study Assist** | 15 (14.9%) | 99 (9.4%) |
| **Out-of-Scope** | 5 (5.0%) | 53 (5.1%) |
| **Terminations `[END_CHAT]`** | 13 (12.9%) | 100 (9.5%) |
| **Terminations (2 pivots)** | 8 (7.9%) | 47 (4.5%) |
| **Style Flagged** | 20 (19.8%) | 203 (19.4%) |

## Code Leakage Evaluation

| Metric | Evaluation Set | Training Set |
| :--- | :--- | :--- |
| **Transcripts Scanned** | 101 | 1049 |
| **Safe Student Quotes** | 0 | 4 |
| **True Code Leaks** | 0 | 0 |
