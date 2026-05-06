# Class-based Refactor Plan for TMParseOCR

Goal: Convert pipeline scripts into a clean class-based architecture with a single entry point `main.py`. Running `python main.py input.pdf` should execute the full pipeline and produce `output/final_output.csv`.

## Project layout

```
TMParseOCR/
├─ pipelines/
│  ├─ __init__.py
│  ├─ pipeline_runner.py        # class PipelineRunner
│  ├─ data_cleaner.py           # class DataCleaner
│  ├─ pdf_chunker.py            # class PDFChunker
│  ├─ trademark_extractor.py    # class TrademarkExtractor
│  ├─ trademark_filler.py       # class TrademarkFiller
│  └─ translator.py             # class Translator
├─ models.py                    # small dataclasses: ApplicationRecord, PageText, PipelineConfig
├─ utils.py                     # small helpers: file I/O, logging, csv helpers
├─ main.py                      # entry point - orchestrates pipeline sequentially
├─ tests/                       # unit tests per-class
│  ├─ test_data_cleaner.py
│  ├─ test_pdf_chunker.py
│  └─ ...
├─ requirements.txt
└─ README.md
```

## Class responsibilities & method sketches

- PipelineRunner (pipelines/pipeline_runner.py)
  - Responsibilities: high-level orchestration for running pipeline on a target PDF or starting from a CSV.
  - Methods:
    - __init__(config: PipelineConfig)
    - run_from_pdf(pdf_path: str) -> Path  # returns path to raw CSV
    - run_from_csv(csv_path: str) -> Path  # runs downstream steps starting from existing CSV
    - _run_full_pipeline(pdf_path: str) -> Path

- DataCleaner (pipelines/data_cleaner.py)
  - Responsibilities: normalize and clean CSV produced by pipeline scripts.
  - Methods:
    - __init__(settings: dict)
    - clean(input_csv: Path, output_csv: Path) -> None
    - _validate_row(row: dict) -> bool

- PDFChunker (pipelines/pdf_chunker.py)
  - Responsibilities: split input PDF into chunk files suitable for OCR or gemini processing.
  - Methods:
    - __init__(chunk_size: int = 1, out_dir: Path = None)
    - chunk(pdf_path: Path) -> Path  # returns folder with chunks

- TrademarkExtractor (pipelines/trademark_extractor.py)
  - Responsibilities: run OCR/Gemini on PDF chunks and produce a CSV with application_number & trademark_text.
  - Methods:
    - __init__(engine: str = 'gemini', options: dict = None)
    - extract(chunk_dir: Path, out_csv: Path) -> None

- TrademarkFiller (pipelines/trademark_filler.py)
  - Responsibilities: merge extracted trademarks into cleaned main CSV, overwriting trademark_text for matching application_number.
  - Methods:
    - __init__(match_key: str = 'application_number')
    - fill(main_csv: Path, gemini_csv: Path, out_csv: Path) -> None

- Translator (pipelines/translator.py)
  - Responsibilities: translate and validate text fields in the merged CSV.
  - Methods:
    - __init__(target_lang: str = 'en', translator_client: Optional[object] = None)
    - translate(input_csv: Path, output_csv: Path) -> None
    - validate(output_csv: Path) -> bool

Note: the Translator interface is intentionally pluggable. During implementation you'll choose whether it calls Gemini again, a cloud API (Google Translate), or a local lookup. The `translator_client` injected into the constructor should implement a simple `translate(text, target_lang)` interface so tests can inject a stub.

## Data contracts / models (models.py)

- PipelineConfig
  - input_pdf: Path
  - out_dir: Path
  - temp_dir: Path
  - log_level: str
  - pipeline_choice: str = 'pipeline'  # one of 'pipeline' | 'pipeline_2'
  - clean_temp: bool = False            # whether to delete temp_dir after successful run
  - preserve_intermediates: bool = True # whether to keep intermediate CSVs/chunks
  - output_prefix: str = 'main'         # prefix for output filenames (e.g. job1_raw.csv)

- ApplicationRecord
  - application_number: str
  - trademark_text: str
  - other_fields: dict

- PageText
  - page_number: int
  - text: str

Use dataclasses for these models so tests can construct them easily.

Notes:
- `PipelineConfig` fields are configurable from CLI or programmatic usage; prefer passing a `PipelineConfig` instance to `PipelineRunner` rather than relying on globals.

Default behaviors and safety:
- `output_prefix` ensures you can run multiple jobs in the same `out_dir` without clobbering files (e.g., `job1_raw.csv`, `job2_raw.csv`).
- `preserve_intermediates` default True helps debugging; CI/integration runs can set it False to save disk.

## Pseudocode for main.py

```
# main.py pseudocode
import argparse
from pathlib import Path
from pipelines.pipeline_runner import PipelineRunner
from models import PipelineConfig

if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument('input_pdf', help='Path to input PDF or path to existing CSV if --from-csv used')
  parser.add_argument('--from-csv', action='store_true', help='Start from an existing CSV instead of running pipeline')
  parser.add_argument('--out-dir', default='output')
  parser.add_argument('--pipeline', choices=['pipeline', 'pipeline_2'], default='pipeline')
  parser.add_argument('--preserve-intermediates', dest='preserve_intermediates', action='store_true')
  parser.add_argument('--no-preserve-intermediates', dest='preserve_intermediates', action='store_false')
  parser.add_argument('--clean-temp', action='store_true')
  parser.add_argument('--output-prefix', default='main')
  args = parser.parse_args()

  config = PipelineConfig(
    input_pdf=Path(args.input_pdf),
    out_dir=Path(args.out_dir),
    temp_dir=Path(args.out_dir) / 'tmp',
    log_level='INFO',
    pipeline_choice=args.pipeline,
    preserve_intermediates=args.preserve_intermediates,
    clean_temp=args.clean_temp,
    output_prefix=args.output_prefix,
  )
  runner = PipelineRunner(config)

  if args.from_csv:
    raw_csv = Path(args.input_pdf)
    runner.run_from_csv(raw_csv)
  else:
    runner.run_from_pdf(Path(args.input_pdf))
```

Inside `PipelineRunner._run_full_pipeline` the steps will be:

1. run pipeline (existing pipeline logic moved into pipelines/pipeline_runner.py) -> `raw_csv`
2. DataCleaner.clean(raw_csv) -> `cleaned_csv`
3. PDFChunker.chunk(pdf_path) -> `chunk_dir`
4. TrademarkExtractor.extract(chunk_dir) -> `gemini_csv`
5. TrademarkFiller.fill(cleaned_csv, gemini_csv) -> `merged_csv`
6. Translator.translate(merged_csv) -> `final_output.csv`

Each class should log actions and raise clear exceptions on failures. The `PipelineRunner` will catch exceptions and either retry or abort with a useful message.

## Logging and utilities

- `utils.py` should expose a `get_logger(name)` helper that configures a single logger used across classes. The logger must include timestamp, level, module, and message, and write to both console and an optional file in `out_dir/logs/pipeline.log`.

## Temp directories and cleanup

- `PipelineConfig.temp_dir` will be a Path under `out_dir/tmp/` by default. `PipelineRunner` must ensure the temp directory exists at pipeline start.
- By default the pipeline will preserve intermediate CSVs and chunk folders under `out_dir/` for debugging. Add a `--clean-temp` CLI flag to delete `temp_dir` after a successful run (or `--keep-temp` to retain them). If an error occurs, the pipeline should not auto-delete temp files to aid debugging.

## Outputs and preservation

- Default output layout (under `out_dir`):
  - `main_raw.csv` — raw CSV produced by the chosen test pipeline
  - `main_cleaned.csv` — output of `DataCleaner`
  - `pdf_chunks/` — folder with chunked PDF pages
  - `gemini_trademarks.csv` — output of `TrademarkExtractor`
  - `main_merged.csv` — updated CSV after `TrademarkFiller`
  - `main_translated.csv` — final translated CSV
  - `logs/pipeline.log` — pipeline logs

You can add `--preserve-intermediates` CLI flag (default: True) to keep these files. If set to False, only the final `main_translated.csv` is kept and intermediates are removed at the end.

## Testing strategy

- Unit tests per-class focusing on public methods using small fixtures.
- Mock external services (OCR/Gemini/translation) in tests to make them fast and deterministic.
- Integration test that runs `main.py` with a small sample PDF and asserts the final CSV exists and matches expected columns.

## How this keeps things modular and testable

- Each class has a single responsibility and may be tested in isolation.
- Small method surface areas make mocking and stubbing easy.
- The entry point (`main.py`) only composes the classes — orchestration logic is minimal.

## Next steps I will take (if you want me to proceed)

1. Run a codebase scan to locate existing functions and determine how to split logic into the classes above.
2. Create the `pipelines/` folder and scaffold the class files with method signatures and docstrings (no heavy refactor yet).
3. Implement adapter wrappers to call existing script-level functions from the new classes.
4. Run tests and iterate.

If you'd like me to start implementing the scaffolding now, confirm and I'll proceed to scan the codebase and scaffold `pipelines/` files.
