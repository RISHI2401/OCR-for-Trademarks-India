import os
import re
import csv
import sys
import math
import time
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Dict, Any, Tuple

from pdf2image import convert_from_path, pdfinfo_from_path
from PIL import Image
import pytesseract
from pytesseract import Output

# ───────────────────────────────────────────────────────────────────────────────
# Tesseract exe path will be set at runtime by run_pipeline() if provided.
# ───────────────────────────────────────────────────────────────────────────────

# ---------------- Helpers & Patterns (Upgraded) ----------------
DATE_PAT = re.compile(r"(\d{1,2})[\/\.\-\s](\d{1,2})[\/\.\-\s](\d{2,4})")
JOURNAL_PAT = re.compile(
    r"Trade\s*Marks\s*Journal\s*No:\s*(\d+)\s*,\s*(\d{1,2}.?\d{1,2}.?\d{2,4})\s*Class\s*(\d+)",
    re.IGNORECASE,
)
CLASS_ONLY_PAT = re.compile(r"^\s*Class\s*(\d+)", re.IGNORECASE)
APP_PAT = re.compile(r"\b(\d{7})\b\s+(\d{1,2}.?\d{1,2}.?\d{2,4})") # More specific: 7 digits
CITY_CHOICES = ["Ahmedabad", "Chennai", "Kolkata", "Delhi", "Mumbai", "IR DIVISION"]
TESS_CONFIG = "--oem 3 --psm 3"

def ensure_dirs(*paths: Path):
    for p in paths: p.mkdir(parents=True, exist_ok=True)

def clean_line(s: str) -> str:
    if not s: return ""
    return re.sub(r"\s+", " ", s.replace("—", "-").replace("–", "-").replace("\u00a0", " ")).strip()

def normalize_date(s: str) -> str:
    if not s: return ""
    m = DATE_PAT.search(s)
    if not m: return ""
    d, mth, yr = map(int, m.groups())
    if yr < 100: yr = 1900 + yr if yr >= 50 else 2000 + yr
    return f"{max(1, min(31, d)):02d}/{max(1, min(12, mth)):02d}/{yr:04d}"

def find_city(line: str) -> str:
    for c in CITY_CHOICES:
        if c.lower() == (line or "").strip().lower(): return c
    return ""

def classify_goods_or_services(class_no: str, description: str) -> str:
    try:
        c = int(class_no)
        if 1 <= c <= 34: return "goods"
        if 35 <= c <= 45: return "services"
    except (ValueError, TypeError): pass
    desc = (description or "").lower()
    if any(k in desc for k in ["product", "manufactur", "chemical", "machine", "material", "adhesive"]): return "goods"
    if any(k in desc for k in ["service", "consult", "repair", "install", "training", "transport"]): return "services"
    return "goods"

def remove_trailing_page_marker(text: str) -> str:
    if not text: return text
    t = text.rstrip()
    for pat in [r"(?:\s*[-–—]?\s*\(?\bPage\s*\d{1,4}\b\)?)\s*$", r"(?:\s*[-–—]?\s*\(?\b\d{1,4}\b\)?)\s*$", r"(?:\s*TMJ\s*\d{1,5})\s*$"]:
        t = re.sub(pat, "", t, flags=re.IGNORECASE).rstrip()
    return t

def crop_logo_between(page_img: Image.Image, journal_no: str, application_number: str) -> Image.Image | None:
    """More robust logo cropping using general header text and better fallbacks."""
    try:
        data = pytesseract.image_to_data(page_img, lang="eng", output_type=Output.DICT, config=TESS_CONFIG)
        page_w, page_h = page_img.size
        def digits_only(s): return re.sub(r"\D", "", s or "")

        # Find the bottom of the journal header
        journal_header_text_candidates = ["Trade", "Marks", "Journal", journal_no]
        found_j_indices = [i for i, txt in enumerate(data["text"]) if any(candidate in txt for candidate in journal_header_text_candidates)]
        found_j_bottom = 0
        if found_j_indices:
            last_header_word_idx = max(found_j_indices, key=lambda i: data["top"][i] + data["height"][i])
            found_j_bottom = data["top"][last_header_word_idx] + data["height"][last_header_word_idx]

        # Find the top of the application number line
        found_a = next((i for i, txt in enumerate(data["text"]) if digits_only(txt) == digits_only(application_number)), None) if application_number else None

        # Primary strategy: Crop between header and application number
        if found_j_bottom > 0 and found_a is not None:
            top_a = int(data["top"][found_a])
            pad = max(5, int(0.01 * page_h))
            crop_top, crop_bottom = max(0, found_j_bottom + pad), max(0, top_a - pad)
            if crop_bottom > crop_top + 20: # Ensure crop height is reasonable
                return page_img.crop((0, crop_top, page_w, crop_bottom))

        # Fallback strategy: Crop a region above the application number
        if found_a is not None:
            top_a, h_a = int(data["top"][found_a]), int(data["height"][found_a])
            crop_top_fallback = max(0, top_a - int(page_h * 0.25))
            crop_bottom_fallback = max(0, top_a - int(h_a * 0.2))
            if crop_bottom_fallback > crop_top_fallback:
                return page_img.crop((0, crop_top_fallback, page_w, crop_bottom_fallback))

        # Last resort fallback: Crop the top 10-30% of the page
        return page_img.crop((0, int(page_h * 0.10), page_w, int(page_h * 0.30)))
    except Exception:
        page_w, page_h = page_img.size
        return page_img.crop((0, int(page_h * 0.10), page_w, int(page_h * 0.30)))

def calculate_accuracy(data: dict) -> tuple[float, str]:
    """Calculates a more comprehensive confidence score and generates validation notes."""
    score = 1.0; notes = []
    if not data.get("application_number"): score -= 0.3; notes.append("Application Number not found.")
    if not data.get("owner_name"): score -= 0.15; notes.append("Owner Name not found.")
    if not data.get("owner_address"): score -= 0.15; notes.append("Owner Address not found.")
    if not data.get("goods_services_description"): score -= 0.15; notes.append("Goods/Services Description not found.")
    if not data.get("journal_no"): score -= 0.05; notes.append("Journal No. not found.")
    if data.get("goods_services_description") and len(data["goods_services_description"]) < 20: score -= 0.05; notes.append("Description may be truncated.")
    if data.get("owner_address") and len(data["owner_address"]) < 15: score -= 0.05; notes.append("Owner Address seems too short.")
    return max(0.0, round(score, 2)), "; ".join(notes)

def extract_details_from_block(chunk_lines: List[str]) -> Dict[str, str]:
    """Helper to extract owner details from a specific text block for one record."""
    data = {"owner_name": "", "owner_address": "", "used_since": "", "status": "pending", "registration_city": "", "goods_services_description": ""}
    lines = chunk_lines[1:]; idx = 0 # Skip the first line which is the app number line

    # Owner Name
    owner_name_parts = []
    if idx < len(lines):
        owner_name_parts.append(lines[idx]); idx += 1
        if idx < len(lines) and re.search(r"^\s*trading as", lines[idx], re.IGNORECASE):
            owner_name_parts.append(lines[idx]); idx += 1
    data["owner_name"] = " ".join(owner_name_parts)

    # Owner Address
    address_end_pat = re.compile(
        r"(Address for service|Address for Service|Proposed to be Used|Proposed to be used|Used Since|"
        r"Attorney address|Attorney Address|Attorney’s address|Agents address|Agent address|Agent’s address|"
        r"MANUFACTURER|MERCHANT|INDIAN INHABITANT|proprietor of|Proprietor of|"
        r"through its director|Through its Director|carrying on business as|"
        r"SOLE PROPRIETOR|Sole Proprietor|PARTNERSHIP FIRM|SINGLE FIRM|PROPRIETORSHIP CONCERN|INDIVIDUAL|individual|Individual|PROPRIETOR|"
        r"A PROPRIETORSHIP FIRM|Proprietorship Firm|PRIVATE LIMITED|PVT LTD|PUBLIC LIMITED|LIMITED|"
        r"INDIAN COMPANY|COMPANY INCORPORATED|BODY INCORPORATE|INDIAN NATIONAL|LLP|"
        r"LIMITED LIABILITY PARTNERSHIP|ONE PERSON COMPANY|OPC PRIVATE LIMITED|Joint Applicant|"
        r"JOINT APPLICANTS|THE TRADE MARK ACT-1999|Registered Partnership Firm|Partnership Concern|"
        r"Hindu Undivided Family|Trust|Society|"
        r"REGISTRATION OF THIS TRADE MARK SHALL GIVE NO RIGHT|MARK SHALL BE USED AS A WHOLE|"
        r"THIS IS CONDITION OF REGISTRATION|The trade mark is restricted to use|For Sale in the State of|"
        r"Associated with|No exclusive right|No claim over|Restrained to use|Subject to|Confined to|"
        r"Active|Abandoned|Withdrawn|Registered|Objected|Refused|"
        # --- New additions ---
        r"trading as|Also trading as|trading in the name and style of|"
        r"an Indian national|a company incorporated under the laws of|"
        r"a partnership firm|a registered partnership firm|"
        r"body corporate|a body corporate|"
        r"a private limited company|Pvt\. Ltd\.|"
        r"a limited liability partnership| a company organized under the laws of India|"
        r"An Indian Company|whose address is|"
        r"a single firm|a sole proprietorship concern|"
        r"A Trust|A Society|A Hindu Undivided Family|class| Class|"
        r"Proprietorship|Co-operative Society|Manufacturer & Merchant|"
        r"A corporation duly organized and existing under the laws of India|Service Provider| India Service Provider)",
        re.IGNORECASE
    )
    addr_lines = []
    while idx < len(lines) and not address_end_pat.search(lines[idx]):
        addr_lines.append(lines[idx]); idx += 1
    data["owner_address"] = clean_line(" ".join(addr_lines))

    # Remaining Details
    remaining_lines = lines[idx:]; desc_start_idx = 0
    for i, ln in enumerate(remaining_lines):
        if "Proposed to be Used" in ln:
            data["used_since"] = ""; desc_start_idx = max(desc_start_idx, i + 1)
        elif mdate := re.search(r"Used\s*Since[:\-\s]*([0-9\/\.\-\s]{4,})", ln, re.IGNORECASE):
            data["used_since"] = normalize_date(mdate.group(1)); desc_start_idx = max(desc_start_idx, i + 1)
        if mc := find_city(ln):
            data["registration_city"] = mc; desc_start_idx = max(desc_start_idx, i + 1)

    # Goods/Services Description
    if desc_start_idx < len(remaining_lines):
        desc_text = " ".join(remaining_lines[desc_start_idx:])
        data["goods_services_description"] = remove_trailing_page_marker(clean_line(desc_text))

    data["status"] = "registered" if data["used_since"] else "pending"
    return data

def process_page_improved(image_path: Path, abs_page_idx: int, logos_dir_abs: Path, project_root_name: str, last_known_journal_no: str, last_known_reg_date: str) -> Tuple[int, List[List[Any]], Dict[str, str]]:
    """
    Processes a single page image, capable of finding multiple records per page
    and using carried-forward journal info.
    """
    page_img = Image.open(image_path)
    full_text = pytesseract.image_to_string(page_img, lang="eng", config=TESS_CONFIG)
    
    # 1. Find journal info on the current page or use last known values.
    j_match = JOURNAL_PAT.search(full_text)
    page_found_info = {}
    if j_match:
        journal_no, reg_date, nice_classes = j_match.group(1), normalize_date(j_match.group(2)), j_match.group(3)
        page_found_info = {"journal_no": journal_no, "reg_date": reg_date}
    else:
        journal_no, reg_date = last_known_journal_no, last_known_reg_date
        class_match = CLASS_ONLY_PAT.search(full_text)
        nice_classes = class_match.group(1) if class_match else ""

    # 2. Find all application number entries on the page.
    app_matches = list(re.finditer(APP_PAT, full_text))
    if not app_matches:
        return abs_page_idx, [], page_found_info

    all_records_on_page = []
    content_start_pos = j_match.end() if j_match else (CLASS_ONLY_PAT.search(full_text).end() if CLASS_ONLY_PAT.search(full_text) else 0)
    
    # 3. Iterate through each found application record.
    for i, current_match in enumerate(app_matches):
        app_no, filing_date = current_match.group(1), normalize_date(current_match.group(2))
        
        # 4. Define text boundaries for the current record.
        record_start_pos = current_match.start()
        record_end_pos = app_matches[i+1].start() if i + 1 < len(app_matches) else len(full_text)
        record_chunk = full_text[record_start_pos:record_end_pos]
        
        # 5. Extract Trademark Text (text between previous record and this one).
        prev_record_end_pos = app_matches[i-1].end() if i > 0 else content_start_pos
        tm_text_chunk = full_text[prev_record_end_pos:record_start_pos]
        tm_lines = [clean_line(ln) for ln in tm_text_chunk.splitlines() if clean_line(ln)]
        tm_lines_filtered = [ln for ln in tm_lines if "priority claimed from" not in ln.lower() and not JOURNAL_PAT.search(ln)]
        trademark_text = " ".join(tm_lines_filtered)

        # 6. Extract owner, address, etc., from the record's main text block.
        chunk_lines = [clean_line(ln) for ln in record_chunk.splitlines() if clean_line(ln)]
        details = extract_details_from_block(chunk_lines)

        # 7. Save Logo Image
        logo_filename = f"{app_no}.png" if app_no else f"page_{abs_page_idx}_record_{i+1}_logo.png"
        absolute_logo_path = logos_dir_abs / logo_filename
        try:
            logo_img = crop_logo_between(page_img, journal_no, app_no)
            if logo_img: logo_img.save(absolute_logo_path, "PNG")
        except Exception as e:
            print(f"Warning: Could not save logo for page {abs_page_idx}, app {app_no}: {e}")
        
        try:
            path_parts = absolute_logo_path.parts
            base_index = path_parts.index(project_root_name)
            image_url_value = Path(*path_parts[base_index:]).as_posix()
        except (ValueError, IndexError): image_url_value = str(absolute_logo_path.as_posix())
            
        # 8. Assemble the final row for the CSV.
        business_type = classify_goods_or_services(nice_classes, details["goods_services_description"])
        payload = {"journal_no": journal_no, "application_number": app_no, "owner_name": details["owner_name"], "owner_address": details["owner_address"], "goods_services_description": details["goods_services_description"]}
        confidence, notes = calculate_accuracy(payload)

        final_row = [
            journal_no, reg_date, nice_classes,
            trademark_text, "", # trademark_text, trademark_text_devanagari
            image_url_value,
            app_no, filing_date,
            clean_line(details["owner_name"]), "", # owner_name, owner_name_devanagari
            clean_line(details["owner_address"]),
            details["used_since"], details["status"],
            details["registration_city"], details["goods_services_description"],
            business_type, confidence, notes
        ]
        all_records_on_page.append(final_row)
            
    return abs_page_idx, all_records_on_page, page_found_info


def render_pages_to_pngs(pdf_path: Path, out_pages_dir: Path, start_page: int, end_page: int, offset: int = 0):
    print(f"Rendering pages {start_page}-{end_page} from PDF -> PNGs with starting index {start_page + offset}")
    ensure_dirs(out_pages_dir)
    # Increased thread_count for potentially faster rendering
    rendered_images = convert_from_path(str(pdf_path), dpi=300, first_page=start_page, last_page=end_page, fmt="png", thread_count=4)
    for i, img in enumerate(rendered_images):
        output_page_num = (start_page + i) + offset
        img.save(out_pages_dir / f"{output_page_num}.png", "PNG")

def main():
    pass


def run_pipeline(pdf_path: str | Path,
                 output_tag: str = "pipeline_output",
                 project_root: str | Path = ".",
                 start: int | None = None,
                 end: int | None = None,
                 batch_size: int = 50,
                 max_workers: int | None = None,
                 skip_render: bool = False,
                 page_number_offset: int = 0,
                 tesseract_cmd: str | None = None):
    """Programmatic entrypoint for the pipeline. Keeps the original behavior but
    allows other code to import and call this function.

    Returns path to the produced CSV file on success.
    """
    start_time = time.monotonic()
    
    # ------------------- NEW BLOCK TO HANDLE MULTIPROCESSING ON MAC -------------------
    # Force 'spawn' start method for cross-platform compatibility, especially for macOS.
    import multiprocessing
    # This check ensures it's only set once.
    if multiprocessing.get_start_method(allow_none=True) != 'spawn':
        multiprocessing.set_start_method('spawn', force=True)
    # ------------------------------------------------------

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found at '{pdf_path}'")

    project_root = Path(project_root).resolve(); project_root_name = project_root.name
    out_root = project_root / "outputs" / output_tag
    out_csv_dir, out_pages_dir, out_logos_dir = out_root / "csv", out_root / "pages", out_root / "logos"
    ensure_dirs(out_csv_dir, out_pages_dir, out_logos_dir)

    total_pages = pdfinfo_from_path(str(pdf_path))['Pages']
    start_page = start or 1
    end_page = end or total_pages

    csv_path = out_csv_dir / f"{output_tag}_{start_page + page_number_offset}-{end_page + page_number_offset}.csv"

    # Configure pytesseract path if provided via argument or environment variable
    import os
    env_tess = os.environ.get('TESSERACT_CMD')
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = str(tesseract_cmd)
    elif env_tess:
        pytesseract.pytesseract.tesseract_cmd = str(env_tess)

    headers = [
        "journal_no", "registration_date", "nice_classes",
        "trademark_text", "trademark_text_devanagari", "image_url",
        "application_number", "filing_date", "owner_name", "owner_name_devanagari",
        "owner_address", "used_since", "status",
        "registration_city", "goods_services_description", "business_type_category",
        "confidence_score", "validation_notes"
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        # Stateful variables to carry journal info across pages
        last_known_journal_no = ""
        last_known_reg_date = ""

        _max_workers = max_workers if max_workers is not None else max(1, (os.cpu_count() or 4) - 1)
        num_batches = math.ceil((end_page - start_page + 1) / batch_size)
        for i, batch_start in enumerate(range(start_page, end_page + 1, batch_size)):
            batch_end = min(batch_start + batch_size - 1, end_page)
            print(f"\n--- Processing Batch {i+1}/{num_batches} (PDF Pages {batch_start}-{batch_end}) ---")

            if not skip_render:
                render_pages_to_pngs(pdf_path, out_pages_dir, batch_start, batch_end, page_number_offset)

            image_paths = [p for p in [out_pages_dir / f"{p + page_number_offset}.png" for p in range(batch_start, batch_end + 1)] if p.exists()]
            if not image_paths: continue

            print(f"Starting OCR on {len(image_paths)} pages...")
            results = {}
            with ProcessPoolExecutor(max_workers=_max_workers) as ex:
                # Pass stateful variables to the processing function
                futures = {ex.submit(process_page_improved, p, int(p.stem), out_logos_dir, project_root_name, last_known_journal_no, last_known_reg_date): p for p in image_paths}
                for fut in as_completed(futures):
                    try:
                        page_idx, rows, found_journal_info = fut.result()
                        results[page_idx] = rows

                        # Update stateful variables if new info is found on the page
                        if found_journal_info.get("journal_no"):
                            last_known_journal_no = found_journal_info["journal_no"]
                            last_known_reg_date = found_journal_info["reg_date"]

                        if rows:
                            print(f"…processed page {page_idx}, found {len(rows)} record(s).")
                        else:
                            print(f"…processed page {page_idx}, found 0 records.")
                    except Exception as e: print(f"ERROR processing page {futures[fut].name}: {e}")

            # Write results for the batch, sorted by page number
            for p_idx in sorted(results.keys()):
                if results[p_idx]:
                    writer.writerows(results[p_idx])

    print(f"\n✅ Done.\nCSV:   {csv_path.as_posix()}\nPages: {out_pages_dir.as_posix()}\nLogos: {out_logos_dir.as_posix()}")

    end_time = time.monotonic()
    duration_seconds = end_time - start_time
    minutes, seconds = divmod(duration_seconds, 60)
    print(f"\n⏱️  Total execution time: {int(minutes)} minutes and {seconds:.2f} seconds.")

    return csv_path
