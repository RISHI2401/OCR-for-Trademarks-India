# TMParseOCR - Technical Handover Document

**Date:** 2026-02-18
**Author:** Outgoing Developer
**Status:** All pipelines working. No known blockers.

---

## 1. System Overview

TMParseOCR extracts structured data from Indian Trade Marks Journal PDFs. It converts PDF pages to images, runs OCR (Tesseract), parses text into structured fields, crops trademark logos, and produces a clean CSV with optional Devanagari transliteration.

### High-Level Flow

```
Input PDF
    │
    ▼
┌─────────────────────────────────┐
│  PDF → PNG (Poppler/pdf2image)  │  Local, no network
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│  OCR (Tesseract via pytesseract)│  Local, no network
│  + Logo Cropping                │
│  + Text Parsing (regex-based)   │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│  Raw CSV (per-page records)     │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│  Data Cleaning (forward-fill,   │  Local, no network
│  type normalization, filtering) │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│  PDF Chunking (PyPDF2)          │  Local, no network
│  Split into ~100-page chunks    │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│  Trademark Extraction (Gemini)  │  *** NETWORK CALL ***
│  Sends PDF chunks to Gemini API │  Optional (--mock-extractor)
│  Returns refined trademark text │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│  Trademark Filler               │  Local, no network
│  Merges Gemini results into CSV │
│  by application_number          │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│  Translation / Transliteration  │  *** NETWORK CALL ***
│  Google Input Tools API         │  English → Devanagari
└──────────────┬──────────────────┘
               │
               ▼
         final.csv
```

---

## 2. File-by-File Architecture

### Core Pipeline Files

| File | Purpose |
|------|---------|
| `main.py` | **Single recommended entry point.** Parses CLI args, runs pipeline, runs post-processing chain. |
| `pipeline.py` | OCR pipeline for standard journals. Contains `run_pipeline()` function. |
| `pipeline_2.py` | OCR pipeline for journals with International Registration (IR) numbers. Contains `run_pipeline()` function. Nearly identical to `pipeline.py` with IR-specific additions. |
| `trademark_extractor.py` | Calls Gemini API to extract trademark text from PDF chunks. Module-level `extract_trademarks(pdf_path)` function. |
| `translation.py` | Transliterates `trademark_text` and `owner_name` to Devanagari using Google Input Tools API. |

### Class Wrappers (`pipelines/` package)

| File | Class | Purpose |
|------|-------|---------|
| `pipelines/pipeline_runner.py` | `CombinedPipeline` | Imports and calls `run_pipeline()` from `pipeline.py` or `pipeline_2.py` |
| `pipelines/data_cleaner.py` | `DataCleaner` | Forward-fill, drop invalid rows, normalize types, find CSVs |
| `pipelines/pdf_chunker.py` | `PDFChunker` | Splits PDF into ~100-page chunks for Gemini processing |
| `pipelines/trademark_extractor.py` | `TrademarkExtractor` | Wraps `trademark_extractor.py` module; supports mock mode |
| `pipelines/trademark_filler.py` | `TrademarkFiller` | Merges Gemini-extracted trademark text into cleaned CSV |

### Utility / Script Files

| File | Purpose |
|------|---------|
| `scripts/combine_csv.py` | Standalone CLI tool to merge multiple CSVs with different column sets |
| `scripts/data_analysis.py` | Standalone audit/validation tool for extracted data quality |
| `scripts/trademark_checklist.csv` | Input checklist for `data_analysis.py` |
| `scripts/eda.ipynb` | Exploratory data analysis notebook |
| `scripts/test_extractor_call.py` | One-off manual test for `trademark_extractor` |
| `scripts/test_wrapper_extractor.py` | One-off manual test for `TrademarkExtractor` wrapper |

### Tests

| File | Purpose |
|------|---------|
| `tests/test_filler_with_mock.py` | Pytest test for `TrademarkFiller.fill()` |

### Config

| File | Purpose |
|------|---------|
| `.env` | API keys (GOOGLE_API_KEY, GEMINI_API_KEY). **Gitignored.** |
| `example .env` | Template showing required env vars |
| `requirements.txt` | Python dependencies |
| `CLASS_REFACTOR_PLAN.md` | Historical planning document (already executed) |

---

## 3. Where Gemini Is Used

**Gemini is used in exactly ONE place:** `trademark_extractor.py`

### What it does:
1. Takes a PDF chunk file path
2. Converts the PDF to base64
3. Sends it to `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent`
4. Prompts Gemini to extract trademark text and application numbers as JSON
5. Returns a list of `{"application_number": "...", "trademark_text": "..."}` dicts

### Configuration:
- Model: `gemini-2.5-pro` (hardcoded in `trademark_extractor.py:15`, overridable via GEMINI_MODEL env var... actually NOT currently, it's hardcoded)
- API key: `GOOGLE_API_KEY` environment variable (loaded from `.env`)
- Retry: 3 attempts with exponential backoff for 429/500/503 errors
- Timeout: 300 seconds per request

### Gemini is NOT used for:
- OCR (that's Tesseract)
- Translation (that's Google Input Tools API)
- Data cleaning (that's pandas)

### How to run WITHOUT Gemini:
```bash
# Option 1: Skip post-processing entirely
python main.py input.pdf --pipeline pipeline_2 --no-postprocess

# Option 2: Use mock extractor (generates fake trademark text)
python main.py input.pdf --pipeline pipeline_2 --mock-extractor
```

---

## 4. The Two Pipelines: Differences

Both `pipeline.py` and `pipeline_2.py` share ~90% identical code. The key differences:

| Aspect | `pipeline.py` | `pipeline_2.py` |
|--------|---------------|-----------------|
| Core function | `process_page_improved()` | `process_page_v4()` |
| IR Number | Not extracted | Extracts via `IR_PAT` regex |
| CSV headers | 18 columns | 19 columns (adds `international_registration_no`) |
| Default tag | `pipeline_output` | `pipeline2_output` |

### When to use which:
- **pipeline** - Standard Trade Marks Journal pages (most common)
- **pipeline_2** - Journal pages that contain "International Registration No." entries

### How the pipeline choice works:
1. CLI: `--pipeline pipeline` or `--pipeline pipeline_2`
2. Per-file mapping: `--pipeline-map mapping.csv` (CSV with columns: `pdf,pipeline`)
3. Default: `pipeline`

---

## 5. OCR Engine Details

### Tesseract Configuration
- DPI: 300 (set in `convert_from_path()`)
- Language: `eng`
- Config: `--oem 3 --psm 3` (LSTM engine, fully automatic page segmentation)
- Thread count: 4 for PDF rendering

### How Tesseract Path is Resolved (priority order):
1. `--tesseract-cmd /path/to/tesseract` CLI argument
2. `TESSERACT_CMD` environment variable
3. System PATH (default)

### Text Parsing Strategy
The OCR text is parsed using regex patterns:
- `JOURNAL_PAT` - Extracts journal number, registration date, and class from page headers
- `APP_PAT` - Finds 7-digit application numbers followed by dates
- `CLASS_ONLY_PAT` - Finds standalone "Class N" lines
- `IR_PAT` (pipeline_2 only) - Finds International Registration numbers

Journal info is **carried forward** across pages (if page N has the header, pages N+1... use it until a new header appears).

### Logo Cropping Logic (`crop_logo_between()`)
1. **Primary:** Crop between journal header bottom and application number top
2. **Fallback 1:** Crop region above the application number (25% of page height)
3. **Fallback 2:** Crop top 10-30% of the page

---

## 6. Post-Processing Chain

After the OCR pipeline produces a raw CSV, these steps run sequentially:

### Step 1: Data Cleaning (`DataCleaner.clean()`)
- Replace empty strings with NaN
- Drop rows with missing `journal_no`
- Forward-fill `journal_no`, `registration_date`, `nice_classes`
- Convert `nice_classes` to integer
- Drop `confidence_score` and `validation_notes` columns

### Step 2: PDF Chunking (`PDFChunker.chunk()`)
- Split input PDF into chunks of ~100 pages
- If last chunk is ≤50 pages, merge it with the previous chunk
- Output: `output/outputs/<prefix>/pdf_chunks/`

### Step 3: Trademark Extraction (`TrademarkExtractor.extract()`)
- For each PDF chunk, call `trademark_extractor.extract_trademarks()`
- This sends the chunk to Gemini API
- Output: CSV with `application_number` and `trademark_text` columns
- **Skip with:** `--mock-extractor` or `--no-postprocess`

### Step 4: Trademark Filling (`TrademarkFiller.fill()`)
- Left-merge Gemini results into cleaned CSV on `application_number`
- Gemini's `trademark_text` overwrites OCR's where available
- Existing values are preserved where Gemini didn't return a match

### Step 5: Translation (`translate_csv()`)
- Transliterates `trademark_text` → `trademark_text_devanagari`
- Transliterates `owner_name` → `owner_name_devanagari`
- Uses Google Input Tools API (free, no auth required)

---

## 7. How to Run Locally

### Prerequisites
1. **Python 3.10+**
2. **Tesseract OCR** installed and on PATH
   - Windows: Download from [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki)
   - macOS: `brew install tesseract`
   - Linux: `sudo apt-get install tesseract-ocr`
3. **Poppler** (for pdf2image)
   - Windows: Download and add to PATH
   - macOS: `brew install poppler`
   - Linux: `sudo apt-get install poppler-utils`
4. **Google API Key** (only if using Gemini for trademark extraction)

### Setup
```bash
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
```

### Environment Variables (`.env`)
```
GOOGLE_API_KEY=your-key-here    # Required only for Gemini step
```

### Common Commands

```bash
# Basic run with pipeline_2 (auto-derives output prefix from PDF name)
python main.py path/to/journal.pdf --pipeline pipeline_2

# Run without any network calls (mock extractor, no translation)
python main.py path/to/journal.pdf --pipeline pipeline_2 --mock-extractor

# Run OCR only, skip all post-processing
python main.py path/to/journal.pdf --pipeline pipeline_2 --no-postprocess

# Dry-run: see which pipeline would be used
python main.py path/to/journal.pdf --list-pipelines

# Batch process a directory of PDFs
python main.py --pdf-dir path/to/pdfs/ --pipeline pipeline_2

# With pipeline mapping (per-file pipeline choice)
python main.py --pdf-dir path/to/pdfs/ --pipeline-map mapping.csv
```

### Output Structure
```
output/outputs/<prefix>/
├── csv/
│   ├── <prefix>_<range>.csv          # Raw OCR output
│   ├── <prefix>_<range>_cleaned.csv  # After DataCleaner
│   ├── trademarks.csv                # Gemini extraction results
│   ├── <prefix>_<range>_cleaned_with_trademarks.csv  # After filler
│   └── final.csv                     # After translation
├── pages/                            # Rendered PNG images
├── logos/                            # Cropped trademark logos
└── pdf_chunks/                       # Chunked PDFs (for Gemini)
```

---

## 8. CLI Reference

| Flag | Default | Description |
|------|---------|-------------|
| `input_pdf` (positional) | — | Path to input PDF |
| `--from-csv` | false | Start from existing CSV (skip OCR) |
| `--pipeline` | `pipeline` | Choose `pipeline` or `pipeline_2` |
| `--out-dir` | `output` | Root output directory |
| `--output-prefix` | `main` | Prefix for output folders/files |
| `--auto-prefix-from-pdf` | false | Derive prefix from PDF filename |
| `--pdf-dir` | — | Process all PDFs in directory |
| `--pipeline-map` | — | CSV mapping file (columns: pdf, pipeline) |
| `--no-postprocess` | false | Skip chunk/extract/fill/translate steps |
| `--mock-extractor` | false | Use fake trademark data instead of Gemini |
| `--timestamp-suffix` | false | Append timestamp to output prefix |
| `--tesseract-cmd` | — | Path to tesseract binary |
| `--list-pipelines` | false | Dry-run: show pipeline choices and exit |
| `--csv-name` | — | Explicit CSV filename to use for downstream steps |
| `--default-pdf` | — | Default PDF path if positional not provided |

---

## 9. Common Issues and Debugging

### OCR Quality Issues

**Problem:** Tesseract misreads text, garbled output
- **Fix:** Check DPI (should be 300). Check Tesseract version (v5+ recommended).
- **Debug:** Look at the PNGs in `output/outputs/<prefix>/pages/` — are they clear?

**Problem:** Application numbers not detected
- **Fix:** `APP_PAT` expects exactly 7 digits followed by a date. Some journals may use different formats.
- **Debug:** Print `full_text` in `process_page_improved()` to see raw OCR output.

**Problem:** Journal header not found on page
- **Expected:** Journal info carries forward from previous pages. The first page of a new class section should always have the header.
- **Debug:** Check if `JOURNAL_PAT` regex matches the page's text.

### Logo Cropping Issues

**Problem:** Logos are cut off or include extra text
- The cropping logic relies on finding the journal header and application number positions via OCR.
- If OCR misidentifies positions, the crop region will be wrong.
- **Workaround:** The logo files are saved individually — manual correction is possible.

### Gemini Issues

**Problem:** `GOOGLE_API_KEY environment variable not set`
- Set it in `.env` or pass via environment.

**Problem:** API rate limiting (429 errors)
- Built-in retry with exponential backoff (2s, 4s). After 3 attempts, it fails.
- **Workaround:** Use `--mock-extractor` for testing, or wait and retry.

**Problem:** Gemini returns malformed JSON
- The extractor expects a JSON array of `{"application_number": "...", "trademark_text": "..."}`.
- If Gemini returns invalid JSON, it raises an exception logged as a warning for that chunk.

### Translation Issues

**Problem:** Transliteration returns original English text
- Google Input Tools may not recognize certain words. This is expected for proper nouns.
- Network errors cause graceful fallback to original text.

---

## 10. Technical Debt and Known Limitations

### Code Duplication
- `pipeline.py` and `pipeline_2.py` share ~90% of their code. The IR-specific logic could be parameterized into a single pipeline file. This was a conscious choice to keep things working and avoid risky refactoring.

### Root-level Superseded Files
- `data_cleaning.py`, `pdf_chunker.py`, `trademark_filller.py` (root level) are older versions superseded by their `pipelines/` counterparts. They remain in the repo but are not imported by `main.py`.

### Hardcoded Model
- Gemini model is hardcoded to `gemini-2.5-pro` in `trademark_extractor.py:15`. Should be configurable via env var or CLI flag.

### No Retry for Translation
- `translation.py` has no retry logic for the Google Input Tools API. Individual word failures return the original text silently.

### Multiprocessing Caveat
- Both pipelines force `spawn` start method for macOS compatibility. On Windows, `spawn` is already the default. The `ProcessPoolExecutor` carries state variables (`last_known_journal_no`, `last_known_reg_date`) but updates them from `as_completed` results, which may arrive out of page order within a batch.

### No Progress Persistence
- If the pipeline crashes mid-run, there is no resume capability. The entire batch must be re-run.

### Image URL Paths
- Logo `image_url` values in the CSV use relative paths based on the project root name. These paths may break if the output is moved.

---

## 11. How to Extend the Pipeline

### Adding a New Pipeline Variant
1. Copy `pipeline.py` or `pipeline_2.py`
2. Modify the `process_page_*()` function and regex patterns
3. Add the new choice to `main.py`'s `--pipeline` argument
4. Register it in `pipelines/pipeline_runner.py`

### Adding a New Post-Processing Step
1. Create a new class in `pipelines/`
2. Import and call it in `main.py` after the existing post-processing chain (around line 180-210)

### Changing the Gemini Model
1. Edit `MODEL` in `trademark_extractor.py:15`
2. Or (recommended improvement) add `GEMINI_MODEL` env var support

### Adding a New CSV Column
1. Add the column name to `headers` list in the pipeline file
2. Add extraction logic in `process_page_improved()` or `process_page_v4()`
3. Add the value to the `final_row` list (position must match headers order)

---

## 12. Dependencies

### Python Packages (`requirements.txt`)
| Package | Purpose |
|---------|---------|
| `pdf2image` | PDF → PNG conversion (requires Poppler system binary) |
| `Pillow` | Image manipulation for logo cropping |
| `pytesseract` | Python wrapper for Tesseract OCR engine |
| `pandas` | CSV/DataFrame operations throughout |
| `requests` | HTTP calls to Gemini API and Google Input Tools |
| `tqdm` | Progress bars for translation step |
| `python-dotenv` | Load `.env` file for API keys |
| `pytest` | Test runner |
| `pypdf2` | PDF splitting for chunking |
| `matplotlib` | Used by EDA scripts (not core pipeline) |

### System Dependencies
| Binary | Purpose | Install |
|--------|---------|---------|
| `tesseract` | OCR engine | brew/apt/Windows installer |
| `pdftoppm` (Poppler) | PDF rendering | brew/apt/Windows binary |

---

## 13. Running Tests

```bash
# Run all tests
pytest tests/

# Run specific test
pytest tests/test_filler_with_mock.py -v
```

Note: Test coverage is minimal. Only `TrademarkFiller` has a pytest test. The scripts in `scripts/test_*.py` are manual one-off tests, not part of the pytest suite.

---

## 14. Quick Reference: "I want to..."

| Goal | Command / File |
|------|---------------|
| Run full pipeline on a PDF | `python main.py journal.pdf --pipeline pipeline_2` |
| Run without Gemini | `python main.py journal.pdf --mock-extractor` |
| Run OCR only (no post-processing) | `python main.py journal.pdf --no-postprocess` |
| See what pipeline would be chosen | `python main.py journal.pdf --list-pipelines` |
| Combine multiple output CSVs | `python scripts/combine_csv.py -i dir/ -o out/` |
| Audit data quality | `python scripts/data_analysis.py --data file.csv --checklist scripts/trademark_checklist.csv --outdir reports/` |
| Understand the regex patterns | `pipeline.py` lines 22-29 |
| Change OCR settings | `TESS_CONFIG` in `pipeline.py` line 30 |
| Change Gemini model | `MODEL` in `trademark_extractor.py` line 15 |
| Add a new column to output | Headers in pipeline.py ~line 332, extraction in `process_page_improved()` |
