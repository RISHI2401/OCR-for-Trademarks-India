# Temporary Archive - Index

Files in this folder are **not deleted** but have been identified as unused by the
active pipeline. They are kept here for reference.

**Date archived:** 2026-02-18

---

| File | Original Location | Reason Archived |
|------|-------------------|-----------------|
| `data_cleaning.py` | Root | Superseded by `pipelines/data_cleaner.py` (class-based version). `main.py` imports only the pipelines version. |
| `pdf_chunker.py` | Root | Superseded by `pipelines/pdf_chunker.py` (class-based version). `main.py` imports only the pipelines version. |
| `trademark_filller.py` | Root | Superseded by `pipelines/trademark_filler.py`. Note: the root file had a triple 'l' typo in the filename. |
| `CLASS_REFACTOR_PLAN.md` | Root | Historical planning document for the class-based refactor. The refactor has been completed. Kept for historical reference. |
| `test_extractor_call.py` | `scripts/` | One-off manual test with hardcoded paths. Not part of the pytest test suite. |
| `test_wrapper_extractor.py` | `scripts/` | One-off manual test with hardcoded paths. Not part of the pytest test suite. |

---

**Important:** The originals still exist at their original locations in the repo.
This archive is a reference copy. If you want to fully remove the originals from
the repo, delete them from their original paths after verifying nothing imports them.

### Files NOT archived (still useful as standalone tools)

| File | Why kept |
|------|----------|
| `scripts/combine_csv.py` | Standalone utility for merging multiple output CSVs. Useful. |
| `scripts/data_analysis.py` | Standalone audit tool for data quality validation. Useful. |
| `scripts/trademark_checklist.csv` | Input for `data_analysis.py`. |
| `scripts/eda.ipynb` | Exploratory notebook. Low priority but harmless. |
