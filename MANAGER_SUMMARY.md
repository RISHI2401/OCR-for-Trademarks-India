# TMParseOCR - Manager Summary

**Date:** 2026-02-18

---

## What This System Does

TMParseOCR converts Indian Trade Marks Journal PDFs into structured CSV data. It reads each page of a PDF, extracts trademark entries (application numbers, owner details, logos, descriptions), and produces a clean spreadsheet.

## Current Status

**Working.** All pipelines run successfully end-to-end. No known blockers.

## Key Architecture Decisions

1. **OCR is done locally** using Tesseract (open-source, free, no API costs).
2. **Gemini AI is used optionally** only to refine trademark text extraction from logos. It can be disabled entirely with a single CLI flag (`--mock-extractor`).
3. **Two pipeline variants exist** -- one for standard journals, one for journals with International Registration numbers.
4. **Single entry point** -- `python main.py` runs everything.

## What Requires Network Access

| Step | Service | Cost | Required? |
|------|---------|------|-----------|
| Trademark text refinement | Google Gemini API | Pay-per-use | **Optional** |
| Devanagari transliteration | Google Input Tools | Free | **Optional** |
| Everything else | None | Free | Local only |

## Handover Documentation

| Document | Purpose |
|----------|---------|
| `README.md` | Setup, how to run, CLI reference |
| `HANDOVER_OCR.md` | Full technical architecture, debugging guide, extension instructions, known limitations |
| `MANAGER_SUMMARY.md` | This document |

## Technical Debt (Non-Urgent)

1. **Code duplication** -- `pipeline.py` and `pipeline_2.py` share ~90% identical code. Could be merged into one parameterized pipeline.
2. **Root-level legacy files** -- Three older script versions (`data_cleaning.py`, `pdf_chunker.py`, `trademark_filller.py`) still exist at the root level but are no longer used. Candidates for archival.
3. **Hardcoded Gemini model** -- The AI model version is hardcoded rather than configurable.
4. **Minimal test coverage** -- Only one automated test exists. More tests would improve confidence for future changes.

## Recommended Next Steps for New Developer

1. Read `HANDOVER_OCR.md` first (full technical walkthrough).
2. Run `python main.py --help` to see all options.
3. Try a test run: `python main.py test.pdf --pipeline pipeline_2 --mock-extractor` (no API key needed).
4. When comfortable, consider merging the two pipelines into one with a flag.
