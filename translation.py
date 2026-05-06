from pathlib import Path
import pandas as pd
import requests
import json
import time
from tqdm import tqdm

def transliterate_text(text_to_transliterate: str) -> str:
    """
    Transliterates a single string from English to Hindi using Google's free
    Input Tools API.
    """
    if not isinstance(text_to_transliterate, str) or not text_to_transliterate.strip():
        return text_to_transliterate

    try:
        url = (
            "https://inputtools.google.com/request?text={}&itc=hi-t-i0-und&num=1"
            "&cp=0&cs=1&ie=UTF-8&oe=UTF-8&app=demopage"
        ).format(requests.utils.quote(text_to_transliterate))

        response = requests.get(url)
        response.raise_for_status()
        
        result = response.json()
        # Ensure the response structure is valid before accessing indices
        if result and len(result) > 1 and len(result[1]) > 0 and len(result[1][0]) > 1 and result[1][0][1]:
            transliterated_word = result[1][0][1][0]
            return transliterated_word
        else:
            return text_to_transliterate

    except (requests.exceptions.RequestException, json.JSONDecodeError, IndexError):
        return text_to_transliterate


def translate_csv(input_csv: str, output_csv: str):
    """
    Programmatic wrapper to transliterate 'trademark_text' and 'owner_name'
    from an input CSV and write to an output CSV.
    """
    print(f"Starting translation for: {input_csv}")
    total_start_time = time.time()
    
    input_path = Path(input_csv)
    if not input_path.exists():
        print(f"❌ Error: Input file for translation not found at '{input_csv}'")
        return

    df = pd.read_csv(input_path)

    # Pre-process text columns, ensuring they exist
    if 'trademark_text' in df.columns:
        df['trademark_text'] = df['trademark_text'].astype(str).fillna('').str.title()
    else:
        df['trademark_text'] = ''

    if 'owner_name' in df.columns:
        df['owner_name'] = df['owner_name'].astype(str).fillna('').str.title()
    else:
        df['owner_name'] = ''

    tqdm.pandas(desc="Transliterating Trademark Text")
    df['trademark_text_devanagari'] = df['trademark_text'].progress_apply(transliterate_text)
    
    tqdm.pandas(desc="Transliterating Owner Name")
    df['owner_name_devanagari'] = df['owner_name'].progress_apply(transliterate_text)

    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding='utf-8')
    
    elapsed_time = time.time() - total_start_time
    print(f"✅ Translation complete. Saved to '{output_path}' in {elapsed_time:.2f}s.")
    return output_csv

# The if __name__ == "__main__" block has been removed to make this a pure module.

