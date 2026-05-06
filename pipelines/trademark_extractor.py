from pathlib import Path
import os
import json
from typing import List

try:
    # Try relative import (when pipelines is used as a package)
    from .. import trademark_extractor as te_mod
except Exception:
    te_mod = None

if te_mod is None:
    # Fallback to absolute import (top-level script)
    try:
        import trademark_extractor as te_mod  # type: ignore
    except Exception:
        te_mod = None


class TrademarkExtractor:
    def __init__(self, api_key: str = None, mock: bool = False):
        # the module uses env var for API key; mock mode can be used for tests
        self.api_key = api_key
        self.mock = mock

    def extract(self, chunks_dir: Path, output_csv: Path) -> Path:
        chunks_dir = Path(chunks_dir)
        if not chunks_dir.exists() or not chunks_dir.is_dir():
            raise FileNotFoundError(f"Chunks directory not found: {chunks_dir}")

        output_csv = Path(output_csv)
        output_csv.parent.mkdir(parents=True, exist_ok=True)

    # If original module is available, try to use it by setting its INPUT_FOLDER and OUTPUT_CSV
        if te_mod:
            # set module-level variables then call main logic by importing
            try:
                te_mod.INPUT_FOLDER = str(chunks_dir)
                te_mod.OUTPUT_CSV = str(output_csv)
                # call the script's main body if present
                if hasattr(te_mod, '__main__'):
                    # not reliable; instead call extract_trademarks per file
                    pass
            except Exception:
                pass

        # Fallback: loop through PDFs and call its extract_trademarks function if present
        extracted = []
        # If mock mode, create simulated records for each PDF chunk
        if self.mock:
            import re
            counter = 1
            for p in sorted(chunks_dir.glob('*.pdf')):
                # Try to extract digits from the filename (common when chunks include numbers).
                # If digits exist, use them concatenated as a numeric application number.
                # Otherwise, generate a deterministic numeric id to ensure the filler can match on digits.
                stem = p.stem
                digits = re.findall(r"\d+", stem)
                if digits:
                    app_num = "".join(digits)
                else:
                    # Fallback numeric id: deterministic and zero-padded
                    app_num = f"900{counter:06d}"
                    counter += 1

                extracted.append({
                    'application_number': app_num,
                    'trademark_text': f"MOCK_TEXT for {p.name}"
                })
        elif te_mod and hasattr(te_mod, 'extract_trademarks'):
            for p in sorted(chunks_dir.glob('*.pdf')):
                try:
                    data = te_mod.extract_trademarks(str(p))
                    extracted.extend(data)
                except Exception as e:
                    print(f"Warning: extractor failed for {p}: {e}")
        else:
            raise RuntimeError("No trademark_extractor module available to perform extraction")

        # Save to CSV (be defensive about headers). Ensure columns are explicit and header is present.
        try:
            import pandas as pd
            # Normalize extracted list into DataFrame with explicit columns
            df = pd.DataFrame(extracted)
            # enforce column order/names
            expected_cols = ['application_number', 'trademark_text']
            for c in expected_cols:
                if c not in df.columns:
                    df[c] = ''
            df = df[expected_cols]
            # sanitize whitespace
            df['application_number'] = df['application_number'].astype(str).str.strip()
            df['trademark_text'] = df['trademark_text'].astype(str).str.strip()

            write_header = True
            if output_csv.exists():
                try:
                    size = output_csv.stat().st_size
                    if size > 0:
                        # read first non-empty line to detect header presence
                        with open(output_csv, 'r', encoding='utf-8', errors='ignore') as fh:
                            first_line = ''
                            for line in fh:
                                if line.strip():
                                    first_line = line.strip()
                                    break
                        if first_line and 'application' in first_line.lower():
                            write_header = False
                        else:
                            # file exists but header missing/invalid; we'll rewrite file with header by
                            # reading old rows and concatenating
                            try:
                                old = pd.read_csv(output_csv, header=None)
                                # if old has two columns, assume they are application_number,trademark_text
                                if old.shape[1] == 2:
                                    old.columns = expected_cols
                                    df = pd.concat([old, df], ignore_index=True)[expected_cols]
                                # else, fall back to overwriting with new df
                            except Exception:
                                # fall back to overwrite
                                pass
                except Exception:
                    # If any stat/read fails, default to writing header
                    write_header = True

            # Now write: if header needed, write/overwrite; else append without header
            if write_header:
                df.to_csv(output_csv, index=False, encoding='utf-8')
            else:
                df.to_csv(output_csv, mode='a', header=False, index=False, encoding='utf-8')
            return output_csv
        except Exception as e:
            raise RuntimeError(f"Failed to write trademark CSV: {e}")
