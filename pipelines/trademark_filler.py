from pathlib import Path
import pandas as pd


class TrademarkFiller:
    def __init__(self):
        pass

    def fill(self, main_csv: Path, trademark_csv: Path, output_csv: Path) -> Path:
        main_csv = Path(main_csv)
        trademark_csv = Path(trademark_csv)
        output_csv = Path(output_csv)

        if not main_csv.exists():
            raise FileNotFoundError(f"Main CSV not found: {main_csv}")
        if not trademark_csv.exists():
            raise FileNotFoundError(f"Trademark CSV not found: {trademark_csv}")

        df = pd.read_csv(main_csv)
        dict_df = pd.read_csv(trademark_csv)

        # Normalize column names
        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
        dict_df.columns = dict_df.columns.str.strip().str.lower().str.replace(" ", "_")

        # Ensure application_number is comparable: coerce to string and strip non-digit chars
        if 'application_number' in df.columns:
            df['application_number'] = df['application_number'].astype(str).str.replace(r"\D", "", regex=True)
        if 'application_number' in dict_df.columns:
            dict_df['application_number'] = dict_df['application_number'].astype(str).str.replace(r"\D", "", regex=True)

        # Merge and overwrite trademark_text when available
        merged = df.merge(dict_df, on="application_number", how="left", suffixes=("", "_new"))
        if 'trademark_text_new' in merged.columns:
            merged['trademark_text'] = merged['trademark_text_new'].combine_first(merged['trademark_text'])
            merged = merged.drop(columns=['trademark_text_new'])

        output_csv.parent.mkdir(parents=True, exist_ok=True)
        merged.to_csv(output_csv, index=False)
        return output_csv
