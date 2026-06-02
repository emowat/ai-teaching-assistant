# Synthetic C++ Dataset Statistics

## Dataset Distribution

| Metric | Evaluation Set | Training Set |
| :--- | :--- | :--- |
| **Total Transcripts** | 162 | 1292 |
| **Homework Assist** | 142 (87.7%) | 1140 (88.2%) |
| **Study Assist** | 15 (9.3%) | 99 (7.7%) |
| **Out-of-Scope** | 5 (3.1%) | 53 (4.1%) |
| **Terminations `[END_CHAT]`** | 14 (8.6%) | 101 (7.8%) |
| **Terminations (2 pivots)** | 9 (5.6%) | 48 (3.7%) |
| **Paste Detected** | 26 (16.0%) | 104 (8.0%) |
| **Debug Ideas Unlocked** | 201 (total tags) | 2482 (total tags) |
| **Style Flagged** | 11 (6.8%) | 149 (11.5%) |

## Code Leakage Evaluation

| Metric | Evaluation Set | Training Set |
| :--- | :--- | :--- |
| **Transcripts Scanned** | 162 | 1292 |
| **Safe Student Quotes** | 0 | 4 |
| **True Code Leaks** | 0 | 0 |
