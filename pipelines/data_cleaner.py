from pathlib import Path
import pandas as pd
import numpy as np
from typing import Union


class DataCleaner:
    """A small class encapsulating the data cleaning logic from data_cleaning.py

    Usage:
        cleaner = DataCleaner()
        cleaned_path = cleaner.clean(input_csv_path, output_csv_path)
    """

    def __init__(self, columns_to_ffill=None):
        if columns_to_ffill is None:
            columns_to_ffill = ['journal_no', 'registration_date', 'nice_classes']
        self.columns_to_ffill = columns_to_ffill

    def clean(self, input_csv: Union[str, Path], output_csv: Union[str, Path]):
        input_csv = Path(input_csv)
        output_csv = Path(output_csv)
        if not input_csv.exists():
            raise FileNotFoundError(f"Input CSV not found: {input_csv}")

        df = pd.read_csv(input_csv)
        # Replace empty strings with NA for object columns only to avoid coercing numeric columns
        obj_cols = df.select_dtypes(include=['object']).columns
        if len(obj_cols) > 0:
            df[obj_cols] = df[obj_cols].replace("", pd.NA)

        # Drop rows with missing journal_no
        if 'journal_no' in df.columns:
            df.dropna(subset=['journal_no'], inplace=True)

        for col in self.columns_to_ffill:
            if col in df.columns:
                df[col] = df[col].ffill()

        if 'nice_classes' in df.columns:
            try:
                df['nice_classes'] = pd.to_numeric(df['nice_classes'], errors='coerce').astype('Int64')
            except Exception:
                pass

        df.drop(columns=['confidence_score', 'validation_notes'], inplace=True, errors='ignore')

        # Only fill missing values in object/string columns with empty string to avoid dtype issues
        obj_cols = df.select_dtypes(include=['object']).columns
        if len(obj_cols) > 0:
            df[obj_cols] = df[obj_cols].fillna("")

        output_csv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_csv, index=False, encoding='utf-8')
        return output_csv

    def find_input_csv(self, csv_dir: Union[str, Path], csv_name: str | None = None, prefix: str | None = None) -> Path | None:
        """Find an input CSV file in csv_dir.

        - If csv_name is provided, prefer exact match (with or without .csv).
        - Else if prefix is provided, find files matching prefix*.csv and return the newest by modification time.
        - Else, return the newest .csv in the directory.
        Returns Path or None if nothing found.
        """
        csv_dir = Path(csv_dir)
        if not csv_dir.exists() or not csv_dir.is_dir():
            return None

        # Exact name supplied
        if csv_name:
            candidate = csv_dir / csv_name
            if candidate.exists():
                return candidate
            if not csv_name.endswith('.csv'):
                candidate2 = csv_dir / (csv_name + '.csv')
                if candidate2.exists():
                    return candidate2

        # Prefixed search
        candidates = []
        if prefix:
            candidates = list(csv_dir.glob(f"{prefix}*.csv"))

        # Fallback: any CSV
        if not candidates:
            candidates = list(csv_dir.glob('*.csv'))

        if not candidates:
            return None

        # pick newest by modification time
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        return newest
