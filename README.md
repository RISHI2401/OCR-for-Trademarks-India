# TMParseOCR

Automated pipeline to extract structured data from Indian Trade Marks Journal PDFs using OCR (Tesseract) with optional Gemini-based trademark text refinement and Devanagari transliteration.

---

## Architecture

```
Input PDF
    |
    +--> PDF to PNG (Poppler)        <-- local, no network
    +--> OCR + Parsing (Tesseract)   <-- local, no network
    +--> Raw CSV
    +--> Data Cleaning               <-- local
    +--> PDF Chunking (PyPDF2)       <-- local
    +--> Trademark Text (Gemini)     <-- NETWORK (optional)
    +--> Merge Results               <-- local
    +--> Transliteration             <-- NETWORK (optional)
    +--> final.csv
```

### Key Fact: Where Gemini IS Used

Gemini is used in **one place only**: `trademark_extractor.py` -- it sends PDF chunks to `gemini-2.5-pro` to extract refined trademark text and application numbers. It does NOT perform OCR (that's Tesseract).

Gemini is **fully optional**. Use `--mock-extractor` or `--no-postprocess` to skip it entirely.

---

## Project Structure

```
TMParseOCR/
+-- main.py                        # Single entry point (recommended)
+-- pipeline.py                    # OCR pipeline for standard journals
+-- pipeline_2.py                  # OCR pipeline for IR number journals
+-- trademark_extractor.py         # Gemini API integration
+-- translation.py                 # Devanagari transliteration
+-- pipelines/                     # Class-based wrappers
|   +-- pipeline_runner.py         # CombinedPipeline (calls pipeline/pipeline_2)
|   +-- data_cleaner.py            # DataCleaner
|   +-- pdf_chunker.py             # PDFChunker
|   +-- trademark_extractor.py     # TrademarkExtractor (wraps trademark_extractor.py)
|   +-- trademark_filler.py        # TrademarkFiller
+-- scripts/                       # Standalone utility scripts
|   +-- combine_csv.py             # Merge multiple CSVs
|   +-- data_analysis.py           # Data quality audit
|   +-- trademark_checklist.csv    # Audit checklist
+-- tests/
|   +-- test_filler_with_mock.py   # Pytest for TrademarkFiller
+-- requirements.txt
+-- HANDOVER_OCR.md                # Full technical handover document
+-- example .env                   # Template for .env file
```

---

## Getting Started

### 1. Prerequisites

| Dependency | Install |
|------------|---------|
| **Python 3.10+** | [python.org](https://www.python.org/) |
| **Tesseract OCR** | Windows: [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) / macOS: `brew install tesseract` / Linux: `sudo apt install tesseract-ocr` |
| **Poppler** | Windows: download binary / macOS: `brew install poppler` / Linux: `sudo apt install poppler-utils` |
| **Google API Key** | Only if using Gemini for trademark extraction |

### 2. Setup

```bash
git clone <repo-url>
cd TMParseOCR
python -m venv venv

# Activate:
# Windows:     venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
```

### 3. Environment Variables

Copy `example .env` to `.env` and set your keys:

```
GOOGLE_API_KEY=your-google-api-key-here
```

Only required if using Gemini. Not needed for `--mock-extractor` or `--no-postprocess` runs.

---

## How to Run

### Basic Usage

```bash
# Standard journal
python main.py path/to/journal.pdf --pipeline pipeline

# Journal with IR numbers
python main.py path/to/journal.pdf --pipeline pipeline_2
```

### Without Network Calls

```bash
# Mock extractor (skip Gemini, still runs OCR + cleaning)
python main.py path/to/journal.pdf --pipeline pipeline_2 --mock-extractor

# OCR only (no post-processing at all)
python main.py path/to/journal.pdf --pipeline pipeline_2 --no-postprocess
```

### Batch Processing

```bash
# Process all PDFs in a directory
python main.py --pdf-dir path/to/pdfs/ --pipeline pipeline_2

# With per-file pipeline mapping
python main.py --pdf-dir path/to/pdfs/ --pipeline-map mapping.csv
```

### Dry Run

```bash
python main.py path/to/journal.pdf --list-pipelines
```

---

## CLI Reference

| Flag | Default | Description |
|------|---------|-------------|
| `input_pdf` | -- | Path to input PDF (positional) |
| `--pipeline` | `pipeline` | `pipeline` (standard) or `pipeline_2` (IR numbers) |
| `--out-dir` | `output` | Root output directory |
| `--output-prefix` | `main` | Prefix for output folders |
| `--auto-prefix-from-pdf` | off | Derive prefix from PDF filename |
| `--from-csv` | off | Start from existing CSV (skip OCR) |
| `--pdf-dir` | -- | Batch process all PDFs in directory |
| `--pipeline-map` | -- | CSV mapping (columns: `pdf`, `pipeline`) |
| `--no-postprocess` | off | Skip chunk/extract/fill/translate |
| `--mock-extractor` | off | Fake trademark data (no Gemini) |
| `--timestamp-suffix` | off | Append timestamp to output prefix |
| `--tesseract-cmd` | -- | Custom path to tesseract binary |
| `--list-pipelines` | off | Dry-run: show choices and exit |
| `--csv-name` | -- | Explicit CSV filename for downstream |
| `--default-pdf` | -- | Fallback PDF path |

---

## Output

```
output/outputs/<prefix>/
+-- csv/
|   +-- <prefix>_<range>.csv              # Raw OCR output
|   +-- <prefix>_<range>_cleaned.csv      # Cleaned
|   +-- trademarks.csv                    # Gemini results
|   +-- ..._cleaned_with_trademarks.csv   # Merged
|   +-- final.csv                         # Translated (final)
+-- pages/                                # Rendered PNGs
+-- logos/                                # Cropped logos
+-- pdf_chunks/                           # PDF chunks (for Gemini)
```

---

## Where Gemini Is Used

| Component | File | Network? | Required? |
|-----------|------|----------|-----------|
| OCR | `pipeline.py` / `pipeline_2.py` | No (Tesseract local) | Yes |
| Trademark text refinement | `trademark_extractor.py` | **Yes (Gemini API)** | **Optional** |
| Transliteration | `translation.py` | **Yes (Google Input Tools)** | **Optional** |
| All other steps | `pipelines/*.py` | No | Yes |

### Running Fully Offline
```bash
python main.py input.pdf --no-postprocess
```
This runs OCR + cleaning only. No network calls. No Gemini. No translation.

---

## Pipeline Variants

| Pipeline | Use When | Key Difference |
|----------|----------|----------------|
| `pipeline` | Standard journal pages | 18 CSV columns |
| `pipeline_2` | Pages with "International Registration No." | 19 columns (adds `international_registration_no`) |

---

## macOS Setup (Tesseract + Poppler)

```bash
brew install tesseract poppler
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Option A: tesseract on PATH (default)
python3 main.py journal.pdf --pipeline pipeline_2

# Option B: explicit path
python3 main.py journal.pdf --pipeline pipeline_2 --tesseract-cmd /opt/homebrew/bin/tesseract

# Option C: env var
export TESSERACT_CMD=/opt/homebrew/bin/tesseract
python3 main.py journal.pdf --pipeline pipeline_2
```

---

## Dependencies

### Python Packages
| Package | Purpose |
|---------|---------|
| `pdf2image` | PDF to PNG conversion |
| `Pillow` | Image manipulation |
| `pytesseract` | Tesseract OCR wrapper |
| `pandas` | Data manipulation |
| `requests` | API calls (Gemini, transliteration) |
| `tqdm` | Progress bars |
| `python-dotenv` | Environment variable loading |
| `pypdf2` | PDF splitting |
| `pytest` | Testing |
| `matplotlib` | EDA scripts (not core pipeline) |

### System Binaries
| Binary | Purpose |
|--------|---------|
| `tesseract` | OCR engine |
| `pdftoppm` (Poppler) | PDF rendering |

---

## Testing

```bash
pytest tests/ -v
```

---

## Further Documentation

- **[HANDOVER_OCR.md](HANDOVER_OCR.md)** -- Full technical handover with debugging guide, architecture deep dive, and extension instructions
