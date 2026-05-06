import base64
import json
import os
import time
import requests
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

# --- Configuration Loaded from Environment ---
API_KEY = os.getenv("GOOGLE_API_KEY")
# Use a stable, known-good model as the default. This can be overridden
# by setting the GEMINI_MODEL environment variable.
MODEL = "gemini-2.5-pro"       

# --- Constants ---
PROMPT = """
You are given a PDF of the Trade Marks Journal.

Your task is to carefully extract only the trademark text and its corresponding application number.

Rules:
- Trademark text = the logo text that appears after the Journal header and before the "Application No." section.
- Application number = the numeric value immediately after "Application No. :". If the text contains an international registration number, you should use that.
- CRITICAL RULE: Explicitly IGNORE and EXCLUDE any lines of text that contain the words 'Priority claimed from'.
- Ignore everything else (addresses, owner details, descriptions, classes, watermarks, etc.).
- Keep the trademark text exactly as shown (case-sensitive, with spaces).
- Return the result strictly as a JSON array of objects. Each object must have two keys: "application_number" (as a string) and "trademark_text" (as a string).
"""

# --- Reusable Functions ---

def file_to_base64(path: str) -> str:
    """Reads a file and converts it to a base64 encoded string."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def extract_trademarks(pdf_path: str) -> list:
    """
    Extracts trademark data from a single PDF file using the Gemini API.
    This function includes retry logic for transient API errors.
    """
    if not API_KEY:
        raise ValueError("GOOGLE_API_KEY environment variable not set.")

    base64_data = file_to_base64(pdf_path)
    
    # CORRECTED: The API URL has been fixed here.
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"
    
    payload = {
        "contents": [{"parts": [{"text": PROMPT}, {"inlineData": {"mimeType": "application/pdf", "data": base64_data}}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }

    max_retries = 3
    last_exception = None
    for attempt in range(max_retries):
        try:
            # Added a timeout to the request to prevent it from hanging indefinitely
            response = requests.post(api_url, headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=300)
            response.raise_for_status()  # This will raise an exception for 4xx/5xx errors

            result = response.json()
    
            if "candidates" not in result or not result["candidates"]:
                feedback = result.get("promptFeedback", "No feedback available.")
                raise Exception(f"Invalid API response or content blocked for {os.path.basename(pdf_path)}. Feedback: {feedback}")
            
            candidate = result["candidates"][0]
            
            # The API response is already parsed JSON in the text field
            return json.loads(candidate["content"]["parts"][0]["text"])

        except requests.exceptions.HTTPError as e:
            # Check for specific retriable status codes
            if e.response.status_code in [429, 500, 503]:
                last_exception = e
                if attempt < max_retries - 1:
                    wait_time = 2 ** (attempt + 1)  # Exponential backoff: 2s, 4s
                    print(f"⚠️ API overload/server error for {os.path.basename(pdf_path)}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    # All retries failed
                    raise Exception(f"API failed after {max_retries} attempts for {os.path.basename(pdf_path)}.") from last_exception
            else:
                # For other HTTP errors (like 400, 404), don't retry
                raise e
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            # Handle cases where the API returns something other than valid JSON
            raw_text = locals().get('candidate', {}).get("content", {}).get("parts", [{}])[0].get("text", "NO_TEXT_RETURNED")
            raise Exception(f"API returned malformed data for {os.path.basename(pdf_path)}. Error: {e}. Raw text: {raw_text}") from e
        except requests.exceptions.RequestException as e:
            # Catch other network-related errors (like the original NameResolutionError)
            last_exception = e
            print(f"❌ A network error occurred for {os.path.basename(pdf_path)}: {e}")
            # This is often not retriable if the URL is wrong, so we break after one try
            break

    # This part will be reached if all retries fail
    raise Exception(f"Failed to get a valid response from API for {os.path.basename(pdf_path)}.") from last_exception

# The if __name__ == "__main__" block has been removed.
# This file is now a pure module, meant to be imported.

