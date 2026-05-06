from pathlib import Path
import pandas as pd
import numpy as np
from typing import Union

class DataCleaner:
    """
    A class to encapsulate the data cleaning logic for the pipeline's CSV output.
    """

    def __init__(self, columns_to_ffill: list = None):
        """
        Initializes the cleaner.

        Args:
            columns_to_ffill (list, optional): A list of column names to apply
                                              a forward-fill operation on.
                                              Defaults to a standard set.
        """
        if columns_to_ffill is None:
            self.columns_to_ffill = ['journal_no', 'registration_date', 'nice_classes']
        else:
            self.columns_to_ffill = columns_to_ffill

    def clean(self, input_csv: Union[str, Path], output_csv: Union[str, Path]) -> Path:
        """
        Loads a CSV, performs cleaning operations, and saves the result.

        Args:
            input_csv (Union[str, Path]): Path to the raw input CSV file.
            output_csv (Union[str, Path]): Path where the cleaned CSV will be saved.

        Returns:
            Path: The path to the saved, cleaned CSV file.
        """
        input_path = Path(input_csv)
        output_path = Path(output_csv)

        if not input_path.exists():
            raise FileNotFoundError(f"Input CSV not found: {input_path}")

        df = pd.read_csv(input_path)
        print(f"✅ Successfully loaded '{input_path.name}'. Shape: {df.shape}")

        # Standardize empty values for reliable processing
        df.replace("", np.nan, inplace=True)
        print("Standardized empty values to NaN for processing.")

        # Filter out rows with a missing 'journal_no'
        if 'journal_no' in df.columns:
            initial_rows = len(df)
            df.dropna(subset=['journal_no'], inplace=True)
            rows_dropped = initial_rows - len(df)
            if rows_dropped > 0:
                print(f"🚮 Dropped {rows_dropped} rows with a missing 'journal_no'.")

        # Apply 'forward fill' to designated columns
        print("\nApplying 'forward fill' to designated columns...")
        for col in self.columns_to_ffill:
            if col in df.columns:
                initial_missing = df[col].isnull().sum()
                if initial_missing > 0:
                    df[col] = df[col].ffill()
                    final_missing = df[col].isnull().sum()
                    print(f"  - Column '{col}': Filled {initial_missing - final_missing} missing values.")
                else:
                    print(f"  - Column '{col}': No missing values to fill.")
            else:
                print(f"  - ⚠️ Warning: Column '{col}' not found in the CSV.")

        # Correct data type for 'nice_classes'
        if 'nice_classes' in df.columns:
            # Use pd.to_numeric with 'coerce' to handle any non-numeric values gracefully
            df['nice_classes'] = pd.to_numeric(df['nice_classes'], errors='coerce').astype('Int64')
            print("\n✅ Converted 'nice_classes' column to integer type.")

        # Remove unnecessary columns
        columns_to_drop = ['confidence_score', 'validation_notes']
        df.drop(columns=columns_to_drop, inplace=True, errors='ignore')
        print(f"🚮 Dropped unnecessary columns: {columns_to_drop}")

        # Finalize by replacing any remaining NaNs with empty strings for a clean output
        df.fillna("", inplace=True)

        # Ensure the output directory exists and save the file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        print(f"\n🎉 Successfully saved final cleaned data to '{output_path}'. Final Shape: {df.shape}")
        
        return output_path
