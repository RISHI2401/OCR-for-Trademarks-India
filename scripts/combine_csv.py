#!/usr/bin/env python3
"""
combine_csvs.py

Combine many CSVs from an input directory into one CSV file, aligning columns by name.
Handles files with different numbers of columns (e.g., 16 vs 17) by using the union of columns.
Generates an audit report detailing per-file columns and any missing columns.

Usage:
    python combine_csv.py --input-dir /path/to/csvs --output-dir /path/to/out
    python combine_csv.py -i ./data -o ./out --dedupe --pattern "*.csv"
    e.g. 
    python "scripts\combine_csv.py" --input-dir "combined_data\input_all_csv" --output-dir "combined_data\output_single_csv"

Outputs:
 - out_dir/combined.csv
 - out_dir/audit_report.csv
 - out_dir/column_order.txt
"""

from pathlib import Path
import argparse
import pandas as pd
import numpy as np
import csv
import sys
import logging

# -------------------------
# Helpers
# -------------------------
def normalize_colname(name: str) -> str:
    """Normalize column name for matching while preserving readability.
    - strip leading/trailing whitespace
    - remove BOM if present
    - collapse multiple internal whitespace to single space
    """
    if name is None:
        return ""
    # Remove BOM (Byte Order Mark) characters sometimes embedded in CSV headers
    name = name.replace("\ufeff", "").replace("\xff\xfe", "").replace("\xfe\xff", "")
    # Strip and collapse whitespace
    name = " ".join(name.strip().split())
    return name

def try_read_csv(path: Path, **kwargs):
    """Attempt to read CSV using default encoding, with fallbacks for encoding errors."""
    try:
        return pd.read_csv(path, **kwargs)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="latin1", **kwargs)
    except Exception as e:
        # Re-raise to let the caller decide; we log outside.
        raise

# -------------------------
# Main combine function
# -------------------------
def combine_csv_files(input_dir: Path,
                      output_dir: Path,
                      pattern: str = "*.csv",
                      dedupe: bool = False,
                      delimiter: str = ",",
                      sample_rows_for_schema: int | None = None,
                      verbose: bool = True):
    """
    Combine CSV files.
    - input_dir: Path to folder with CSV files (non-recursive)
    - output_dir: Path where outputs will be written
    - pattern: glob pattern for files (default *.csv)
    - dedupe: if True, drop exact duplicate rows (after concatenation)
    - delimiter: CSV delimiter to use when reading (default comma)
    - sample_rows_for_schema: if provided, read only this many rows initially for schema discovery
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Setup logging
    log = logging.getLogger("combine_csvs")
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    if not log.handlers:
        log.addHandler(handler)

    files = sorted(input_dir.glob(pattern))
    if len(files) == 0:
        raise FileNotFoundError(f"No files found in {input_dir} matching {pattern}")

    log.info(f"Found {len(files)} files matching {pattern} in {input_dir}")

    # We'll store per-file diagnostics for audit
    audit_rows = []
    # Keep normalized columns in order of first-seen (to build a stable union)
    seen_cols_order = []

    # We'll store dataframes or file paths to read later
    file_read_info = []

    # 1) First pass: discover column names (normalized) across files
    for f in files:
        try:
            # read only header (and optionally a few rows to infer anything)
            # use low_memory=False to avoid dtype warnings
            header_df = try_read_csv(f, sep=delimiter, nrows=0)
            orig_cols = list(header_df.columns)
            # Normalize column names
            norm_cols = [normalize_colname(c) for c in orig_cols]
            # detect duplicates in normalized names within the file
            dup_norm = [c for c in set(norm_cols) if norm_cols.count(c) > 1]
            if dup_norm:
                log.warning(f"File {f.name} has duplicate normalized column names: {dup_norm}. "
                            "Pandas will auto-rename some columns when reading. Consider cleaning source files.")
            # Update seen_cols_order while preserving first-seen order
            for c in norm_cols:
                if c not in seen_cols_order:
                    seen_cols_order.append(c)

            file_read_info.append({
                "path": f,
                "orig_columns": orig_cols,
                "norm_columns": norm_cols,
                "nrows_est": None,
                "error": None
            })
            log.debug(f"Discovered columns in {f.name}: {norm_cols}")
        except Exception as e:
            log.exception(f"Failed to read header from {f.name}: {e}")
            file_read_info.append({
                "path": f,
                "orig_columns": [],
                "norm_columns": [],
                "nrows_est": 0,
                "error": str(e)
            })

    # Compose final column order: prefer seen_cols_order (first-seen), but ensure stable
    final_columns = list(seen_cols_order)  # union in first-seen order

    log.info(f"Final column union ({len(final_columns)}): {final_columns}")

    # 2) Second pass: read each file fully, normalize its columns, align to final_columns
    dfs = []
    for info in file_read_info:
        f = info["path"]
        try:
            # Read with dtype inference. Use low_memory False to avoid mixed dtype warnings.
            df = try_read_csv(f, sep=delimiter, low_memory=False)
            nrows = df.shape[0]
            info["nrows_est"] = nrows

            # Normalize columns in the DataFrame: map original -> normalized
            orig_cols = list(df.columns)
            mapping = {orig: normalize_colname(orig) for orig in orig_cols}
            # If mapping produces duplicate normalized names, pandas will auto-handle when renaming.
            df = df.rename(columns=mapping)

            # If there were duplicate normalized names that resulted in pandas auto-duplicating (e.g. 'col', 'col.1'),
            # we still aim to keep them as-is (they are separate columns). We won't attempt to merge them automatically.
            # Reindex to final columns, adding any missing columns (with NaN)
            # If DataFrame has columns not in final_columns (rare), we append them at the end
            extra_cols = [c for c in df.columns if c not in final_columns]
            if extra_cols:
                # Extend final columns with new ones (this might happen if we didn't see them in "first pass" due to read error)
                for c in extra_cols:
                    if c not in final_columns:
                        final_columns.append(c)
                        log.debug(f"Added new column to final union from {f.name}: {c}")

            df = df.reindex(columns=final_columns)  # missing columns will be NaN

            dfs.append(df)

            # Audit entry
            missing_cols = [c for c in final_columns if c not in list(df.columns) or df[c].isna().all()]
            audit_rows.append({
                "file": str(f.resolve()),
                "filename": f.name,
                "orig_col_count": len(orig_cols),
                "norm_col_count": len(mapping),
                "rows": nrows,
                "missing_columns_count": len([c for c in final_columns if c not in mapping]),
                "missing_columns_example": ", ".join([c for c in final_columns if c not in mapping][:5]),
                "error": ""
            })

            log.info(f"Read {nrows} rows from {f.name}; columns: {len(mapping)} (normalized).")

        except Exception as e:
            log.exception(f"Error reading {f.name}: {e}")
            audit_rows.append({
                "file": str(f.resolve()),
                "filename": f.name,
                "orig_col_count": None,
                "norm_col_count": None,
                "rows": 0,
                "missing_columns_count": None,
                "missing_columns_example": "",
                "error": str(e)
            })

    if len(dfs) == 0:
        raise RuntimeError("No files successfully read; aborting combine.")

    # 3) Concatenate all dataframes
    log.info("Concatenating dataframes...")
    combined = pd.concat(dfs, axis=0, ignore_index=True, sort=False)

    # 4) Optional post-processing: strip whitespace in string columns & standardize empty strings to NaN
    # This helps avoid subtle mismatches
    for col in combined.select_dtypes(include=["object"]).columns:
        combined[col] = combined[col].astype(str).map(lambda x: x.strip() if pd.notna(x) else x)
        # convert empty strings back to NaN
        combined[col] = combined[col].replace({"": np.nan})

    # 5) Optional deduplication
    if dedupe:
        pre = combined.shape[0]
        combined = combined.drop_duplicates(keep="first").reset_index(drop=True)
        post = combined.shape[0]
        log.info(f"Dropped {pre - post} duplicate rows (exact duplicates).")

    # 6) Save outputs
    combined_path = output_dir / "combined.csv"
    audit_path = output_dir / "audit_report.csv"
    col_order_path = output_dir / "column_order.txt"

    # For consistent CSV writing: use quoting minimal and keep index False
    combined.to_csv(combined_path, index=False, quoting=csv.QUOTE_MINIMAL)
    pd.DataFrame(audit_rows).to_csv(audit_path, index=False)
    with open(col_order_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(final_columns))

    log.info(f"Wrote combined CSV to: {combined_path} (rows: {combined.shape[0]}, columns: {combined.shape[1]})")
    log.info(f"Wrote audit report to: {audit_path}")
    log.info(f"Wrote column order to: {col_order_path}")

    return {
        "combined_path": combined_path,
        "audit_path": audit_path,
        "col_order_path": col_order_path,
        "combined_shape": combined.shape
    }

# -------------------------
# CLI entrypoint
# -------------------------
def main():
    parser = argparse.ArgumentParser(description="Combine many CSV files into one (handles different column sets).")
    parser.add_argument("--input-dir", "-i", required=True, help="Directory containing csv files to combine")
    parser.add_argument("--output-dir", "-o", required=True, help="Directory to write combined.csv and reports")
    parser.add_argument("--pattern", "-p", default="*.csv", help="Glob pattern for input CSVs (default: *.csv)")
    parser.add_argument("--delimiter", "-d", default=",", help="CSV delimiter (default comma)")
    parser.add_argument("--dedupe", action="store_true", help="Drop exact duplicate rows in the final combined file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    out = combine_csv_files(input_dir=input_dir,
                            output_dir=output_dir,
                            pattern=args.pattern,
                            dedupe=args.dedupe,
                            delimiter=args.delimiter,
                            verbose=args.verbose)
    print("Done. Outputs:", out)

if __name__ == "__main__":
    main()
