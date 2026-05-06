from pathlib import Path
import pandas as pd
from typing import Union

class TrademarkFiller:
    """
    Merges trademark data extracted by a secondary process (e.g., Gemini API)
    into the main cleaned CSV file.
    """

    def fill(self, main_csv: Union[str, Path], trademark_csv: Union[str, Path], output_csv: Union[str, Path]) -> Path:
        """
        Loads the main CSV and the trademark CSV, merges them on the application
        number, and saves the result to a new file.

        Args:
            main_csv (Union[str, Path]): Path to the main cleaned CSV from the pipeline.
            trademark_csv (Union[str, Path]): Path to the CSV containing the refined
                                             trademark text from the extractor.
            output_csv (Union[str, Path]): Path to save the final merged CSV file.

        Returns:
            Path: The path to the saved, final CSV file.
        """
        main_path = Path(main_csv)
        trademark_path = Path(trademark_csv)
        output_path = Path(output_csv)

        if not main_path.exists():
            raise FileNotFoundError(f"Main CSV not found: {main_path}")
        if not trademark_path.exists():
            raise FileNotFoundError(f"Trademark CSV not found: {trademark_path}")

        df = pd.read_csv(main_path)
        dict_df = pd.read_csv(trademark_path)

        # --- Data Normalization for Robust Merging ---
        # Normalize column names to lowercase and underscores
        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_").str.replace("-", "_")
        dict_df.columns = dict_df.columns.str.strip().str.lower().str.replace(" ", "_").str.replace("-", "_")

        # CRITICAL: Ensure 'application_number' is a clean string of digits for a reliable merge
        if 'application_number' in df.columns:
            df['application_number'] = df['application_number'].astype(str).str.replace(r"\D", "", regex=True)
        if 'application_number' in dict_df.columns:
            dict_df['application_number'] = dict_df['application_number'].astype(str).str.replace(r"\D", "", regex=True)

        print(f"Merging trademark data for {len(dict_df)} entries into the main dataset.")

        # --- Merge and Update ---
        # Perform a left merge to keep all records from the main dataframe
        merged_df = df.merge(dict_df, on="application_number", how="left", suffixes=("", "_new"))
        
        # Use the new trademark text if it exists, otherwise keep the old one
        if 'trademark_text_new' in merged_df.columns and 'trademark_text' in merged_df.columns:
            merged_df['trademark_text'] = merged_df['trademark_text_new'].combine_first(merged_df['trademark_text'])
            # Drop the now-redundant new column
            merged_df.drop(columns=['trademark_text_new'], inplace=True)

        # --- Save Final CSV ---
        output_path.parent.mkdir(parents=True, exist_ok=True)
        merged_df.to_csv(output_path, index=False)
        print(f"🎉 Successfully saved final data with trademarks to '{output_path}'.")
        
        return output_path
