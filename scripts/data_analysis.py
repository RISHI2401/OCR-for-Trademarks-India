#!/usr/bin/env python3
"""
trademark_audit.py

Self-contained script to:
- Load a validation checklist CSV (must have at least: Feature, Validation Rules, Severity)
- Add a Keep_Flag column (to toggle which checks to run)
- Optionally produce a trimmed checklist with only Keep_Flag==True
- Run validations on an extracted data CSV and write a discrepancy report

Dependencies:
- pandas
Install:
    pip install pandas
    
    
Usage:
    - Basic:
    
        python trademark_audit.py --data "/path/to/data.csv" --checklist "/path/to/checklist.csv" --outdir "./reports"
        
    - Create a trimmed checklist and run:
    
        python trademark_audit.py --data data.csv --checklist checklist.csv --outdir ./reports --make-trimmed --trim-defaults
        
    - Force-run all checks (ignore Keep_Flag):
    
        python trademark_audit.py --data data.csv --checklist checklist.csv --outdir ./reports --force-all

"""

import pandas as pd
import re
import argparse
import os
import datetime
from typing import Tuple

# -----------------------
# Core flags to keep by default (trimmed, high-signal)
# -----------------------
CORE_FLAGS = {
    # error_code families we treat as "core" by default
    "DATE_FORMAT",
    "DATE_ORDER",
    "FUTURE_DATE",
    "EMPTY",
    "INVALID_ENUM",
    "INVALID_RANGE",
    "INVALID_FORMAT",
    "DUPLICATE",
    "JOURNAL_INCONSISTENT",
}

# Mapping from features -> default error codes we will run (helps set Keep_Flag)
FEATURE_TO_DEFAULT_FLAGS = {
    "registration_date": ["DATE_FORMAT", "DATE_ORDER", "FUTURE_DATE"],
    "filing_date": ["DATE_FORMAT", "DATE_ORDER"],
    "used_since": ["DATE_FORMAT", "DATE_ORDER"],
    "nice_classes": ["INVALID_RANGE", "NOT_INT"],
    "trademark_text": ["EMPTY"],
    "trademark_text_devanagari": ["NOT_DEVANAGARI"],
    "international_registration_no": ["NOT_NUMERIC"],
    "image_url": ["INVALID_FORMAT", "EMPTY"],
    "application_number": ["FORMAT", "DUPLICATE", "MISSING"],
    "owner_name": ["EMPTY_OR_PLACEHOLDER", "UNEXPECTED_CHARS"],
    "owner_address": ["MISSING", "TOO_SHORT"],
    "status": ["INVALID_ENUM"],
    "registration_city": ["UNKNOWN_CITY", "MISSING"],
    "goods_services_description": ["EMPTY"],
    "business_type_category": ["INVALID_ENUM"],
    "journal_no": ["JOURNAL_INCONSISTENT"],
}

# -----------------------
# Helper validation funcs
# -----------------------
def is_valid_date_str(s: str) -> Tuple[bool, datetime.date]:
    """
    Accepts DD/MM/YYYY or DD-MM-YYYY. Returns (valid, date_or_None).
    Normalizes '-' to '/' before parsing.
    """
    if s is None:
        return False, None
    s = str(s).strip()
    if s == "":
        return False, None
    # normalize dash to slash
    s_norm = s.replace("-", "/")
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s_norm)
    if not m:
        return False, None
    try:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        d = datetime.date(year, month, day)
        return True, d
    except Exception:
        return False, None

def match_regex(val, pattern):
    if pd.isna(val):
        return False
    return re.match(pattern, str(val).strip()) is not None

def normalize_application_number(appl):
    """
    Safe normalization for application_number:
    - If float and integer-like, convert to int
    - Strip surrounding whitespace
    - If string with trailing .0, remove it
    - Return string of digits (if any), otherwise original string
    """
    if pd.isna(appl):
        return appl
    # handle numeric types
    try:
        if isinstance(appl, float):
            if appl.is_integer():
                return str(int(appl))
            else:
                # not integer-like float, return as-is string
                return str(appl)
        if isinstance(appl, int):
            return str(appl)
    except Exception:
        pass
    s = str(appl).strip()
    # remove trailing .0 if present
    if s.endswith(".0"):
        s = s[:-2]
    # remove non-digit characters but keep if all become empty
    digits = re.sub(r"\D+", "", s)
    return digits if digits != "" else s

# -----------------------
# Core audit function
# -----------------------
def run_audit(data_df: pd.DataFrame, checklist_df: pd.DataFrame, only_enabled: bool = True, force_all: bool = False):
    """
    Runs validations using rules from checklist_df.
    checklist_df is expected to have 'Feature', 'Validation Rules', 'Severity', and optional 'Keep_Flag'.
    If only_enabled is True, only rows with Keep_Flag==True are used; if force_all True -> ignore Keep_Flag.
    Returns a DataFrame of issues found.
    """
    # Normalize cols
    checklist_df = checklist_df.copy()
    checklist_df.columns = checklist_df.columns.str.strip()

    if 'Keep_Flag' not in checklist_df.columns:
        checklist_df['Keep_Flag'] = True  # assume enabled if missing

    # Optionally interpret Keep_Flag: if missing or non-boolean, coerce
    checklist_df['Keep_Flag'] = checklist_df['Keep_Flag'].astype(bool)

    # Which features to enforce?
    if force_all:
        enabled_features = checklist_df['Feature'].tolist()
    else:
        enabled_features = checklist_df[checklist_df['Keep_Flag'] == True]['Feature'].tolist()

    # Precompute some patterns and sets
    app_num_regex = r'^\d{6,8}$'
    image_pattern = r'^(output/|http).*\.(jpg|jpeg|png)$'
    status_allowed = {"pending","registered","refused","withdrawn"}
    business_allowed = {"goods","services"}
    known_cities = set(data_df.get('registration_city', pd.Series(dtype=str)).dropna().astype(str).str.strip().unique().tolist())
    known_cities.update({"Delhi","Mumbai","Chennai","Kolkata","Ahmedabad","Bengaluru","Pune","Hyderabad","Jaipur","Surat"})

    issues = []
    seen_appnums = {}
    # If journal_no column missing in data, ensure it's treated gracefully
    journal_values = data_df.get('journal_no', pd.Series(dtype=object)).dropna().unique().tolist()

    for idx, row in data_df.iterrows():
        # normalize app_no for reporting (use raw value for message but normalized for uniqueness)
        raw_app_no = row.get('application_number', None)
        app_no = normalize_application_number(raw_app_no)

        # --- JOURNAL: missing check and inconsistency ---
        if 'journal_no' in enabled_features:
            jval = row.get('journal_no', None)
            if pd.isna(jval) or str(jval).strip() == "":
                issues.append({
                    "row_index": idx,
                    "application_number": app_no,
                    "field": "journal_no",
                    "error_code": "MISSING",
                    "message": "journal_no empty or missing",
                    "severity": "Critical",
                    "autofix_suggestion": "Verify source file; journal_no should be provided"
                })
            else:
                # file-level inconsistency (flag if multiple journal values exist)
                if len(journal_values) > 1:
                    issues.append({
                        "row_index": idx,
                        "application_number": app_no,
                        "field": "journal_no",
                        "error_code": "JOURNAL_INCONSISTENT",
                        "message": f"Multiple journal_no values found in file: {journal_values}",
                        "severity": "Critical",
                        "autofix_suggestion": "Verify source file grouping"
                    })

        # registration_date
        if 'registration_date' in enabled_features:
            valid_reg, reg_dt = is_valid_date_str(row.get('registration_date', None))
            if not valid_reg:
                issues.append({"row_index": idx, "application_number": app_no, "field":"registration_date",
                               "error_code":"DATE_FORMAT","message":f"Invalid registration_date: {row.get('registration_date')}",
                               "severity":"Critical","autofix_suggestion":"Normalize to DD/MM/YYYY or manual review"})
            else:
                if reg_dt > datetime.date.today():
                    issues.append({"row_index": idx, "application_number": app_no, "field":"registration_date",
                                   "error_code":"FUTURE_DATE","message":f"registration_date in future: {row.get('registration_date')}",
                                   "severity":"High","autofix_suggestion":"Check OCR source"})

        # filing_date
        if 'filing_date' in enabled_features:
            valid_filing, filing_dt = is_valid_date_str(row.get('filing_date', None))
            if not valid_filing:
                issues.append({"row_index": idx, "application_number": app_no, "field":"filing_date",
                               "error_code":"DATE_FORMAT","message":f"Invalid filing_date: {row.get('filing_date')}",
                               "severity":"High","autofix_suggestion":"Normalize to DD/MM/YYYY or manual review"})
            else:
                # if reg exists, check order
                valid_reg, reg_dt = is_valid_date_str(row.get('registration_date', None))
                if valid_reg and filing_dt and reg_dt and filing_dt > reg_dt:
                    issues.append({"row_index": idx, "application_number": app_no, "field":"filing_date",
                                   "error_code":"DATE_ORDER","message":f"filing_date {row.get('filing_date')} is after registration_date {row.get('registration_date')}",
                                   "severity":"High","autofix_suggestion":"Verify dates; likely parse/OCR error"})

        # used_since
        if 'used_since' in enabled_features:
            used_raw = row.get('used_since', None)
            if used_raw and str(used_raw).strip() != "":
                valid_used, used_dt = is_valid_date_str(used_raw)
                if not valid_used:
                    issues.append({"row_index": idx, "application_number": app_no, "field":"used_since",
                                   "error_code":"DATE_FORMAT","message":f"Invalid used_since: {used_raw}","severity":"Medium",
                                   "autofix_suggestion":"Normalize or blank"})
                else:
                    valid_filing, filing_dt = is_valid_date_str(row.get('filing_date', None))
                    if valid_filing and used_dt and filing_dt and used_dt > filing_dt:
                        issues.append({"row_index": idx, "application_number": app_no, "field":"used_since",
                                       "error_code":"DATE_ORDER","message":f"used_since {used_raw} is after filing_date {row.get('filing_date')}",
                                       "severity":"Medium","autofix_suggestion":"Verify source"})

        # nice_classes
        if 'nice_classes' in enabled_features:
            nc = row.get('nice_classes', None)
            try:
                nc_int = int(nc)
                # allow 99 as special marker if used in some datasets
                if not (1 <= nc_int <= 45 or nc_int == 99):
                    issues.append({"row_index": idx, "application_number": app_no, "field":"nice_classes",
                                   "error_code":"INVALID_RANGE","message":f"nice_classes {nc} not in 1-45",
                                   "severity":"High","autofix_suggestion":"Map to nearest valid class or manual review"})
            except Exception:
                issues.append({"row_index": idx, "application_number": app_no, "field":"nice_classes",
                               "error_code":"NOT_INT","message":f"nice_classes not integer: {nc}",
                               "severity":"High","autofix_suggestion":"Attempt parse or manual"})

        # trademark_text
        if 'trademark_text' in enabled_features:
            tt = row.get('trademark_text', None)
            if pd.isna(tt) or str(tt).strip() == "":
                issues.append({"row_index": idx, "application_number": app_no, "field":"trademark_text",
                               "error_code":"EMPTY","message":"trademark_text is empty","severity":"High",
                               "autofix_suggestion":"Check OCR output / source"})

        # trademark_text_devanagari
        if 'trademark_text_devanagari' in enabled_features:
            ttd = row.get('trademark_text_devanagari', None)
            if not (pd.isna(ttd) or str(ttd).strip()==""):
                if not re.search(r'[\u0900-\u097F]', str(ttd)):
                    issues.append({"row_index": idx, "application_number": app_no, "field":"trademark_text_devanagari",
                                   "error_code":"NOT_DEVANAGARI","message":"Devanagari text has no Devanagari characters",
                                   "severity":"Medium","autofix_suggestion":"Review transliteration"})

        # international_registration_no
        if 'international_registration_no' in enabled_features:
            irn = row.get('international_registration_no', None)
            if not (pd.isna(irn) or str(irn).strip()==""):
                try:
                    int(irn)
                except Exception:
                    issues.append({"row_index": idx, "application_number": app_no, "field":"international_registration_no",
                                   "error_code":"NOT_NUMERIC","message":f"international_registration_no not numeric: {irn}",
                                   "severity":"Low","autofix_suggestion":"Strip non-digit chars or manual"})

        # image_url
        if 'image_url' in enabled_features:
            img = row.get('image_url', '')
            if pd.isna(img) or str(img).strip() == "":
                issues.append({"row_index": idx, "application_number": app_no, "field":"image_url",
                               "error_code":"EMPTY","message":"image_url empty","severity":"High","autofix_suggestion":"Check image extraction"})
            else:
                if not match_regex(img, image_pattern):
                    issues.append({"row_index": idx, "application_number": app_no, "field":"image_url",
                                   "error_code":"INVALID_FORMAT","message":f"image_url doesn't match expected pattern: {img}",
                                   "severity":"High","autofix_suggestion":"Ensure path starts with output/ or http and ends with .jpg/.png"})

        # application_number (with normalization, missing, format, duplicate checks)
        if 'application_number' in enabled_features:
            raw_appl = row.get('application_number', None)
            appl_norm = normalize_application_number(raw_appl)
            if pd.isna(raw_appl) or str(raw_appl).strip() == "":
                issues.append({"row_index": idx, "application_number": appl_norm, "field":"application_number",
                               "error_code":"MISSING","message":"application_number missing","severity":"Critical","autofix_suggestion":"Manual review"})
            else:
                # use normalized value for format check
                if not match_regex(appl_norm, app_num_regex):
                    issues.append({"row_index": idx, "application_number": appl_norm, "field":"application_number",
                                   "error_code":"FORMAT","message":f"application_number doesn't match 6-8 digits: {raw_appl}",
                                   "severity":"Critical","autofix_suggestion":"Strip non-digits or manual review"})
                appl_s = str(appl_norm).strip()
                if appl_s in seen_appnums:
                    issues.append({"row_index": idx, "application_number": appl_s, "field":"application_number",
                                   "error_code":"DUPLICATE","message":f"Duplicate application_number seen at row {seen_appnums[appl_s]}",
                                   "severity":"Critical","autofix_suggestion":"Resolve duplicates in source"})
                else:
                    # only store normalized digit-string if non-empty
                    if appl_s != "":
                        seen_appnums[appl_s] = idx

        # owner_name
        if 'owner_name' in enabled_features:
            owner = row.get('owner_name', None)
            if pd.isna(owner) or str(owner).strip() == "" or str(owner).strip().upper() in {"N/A","NA","-","NONE"}:
                issues.append({"row_index": idx, "application_number": app_no, "field":"owner_name",
                               "error_code":"EMPTY_OR_PLACEHOLDER","message":f"owner_name is empty or placeholder: {owner}",
                               "severity":"High","autofix_suggestion":"Manual review to fill owner name"})
            else:
                # UNEXPECTED_CHARS informational
                if not re.match(r'^[A-Za-z0-9\s\.\&\,\-\']+$', str(owner).strip()):
                    # Keep lower severity to reduce noise (but still show)
                    issues.append({"row_index": idx, "application_number": app_no, "field":"owner_name",
                                   "error_code":"UNEXPECTED_CHARS","message":f"owner_name contains unexpected chars: {owner}",
                                   "severity":"Low","autofix_suggestion":"Strip problematic chars or manual verification"})

        # owner_address: missing and too-short checks
        if 'owner_address' in enabled_features:
            addr = row.get('owner_address', None)
            if pd.isna(addr) or str(addr).strip() == "":
                issues.append({"row_index": idx, "application_number": app_no, "field":"owner_address",
                               "error_code":"MISSING","message":"owner_address empty or missing","severity":"Low","autofix_suggestion":"Optional"})
            else:
                if len(str(addr).strip()) < 15:
                    issues.append({"row_index": idx, "application_number": app_no, "field":"owner_address",
                                   "error_code":"TOO_SHORT","message":"owner_address too short (<15 chars)","severity":"Low","autofix_suggestion":"Manual review"})

        # status
        if 'status' in enabled_features:
            st = row.get('status', None)
            if pd.isna(st) or str(st).strip()=="" or str(st).strip().lower() not in status_allowed:
                issues.append({"row_index": idx, "application_number": app_no, "field":"status",
                               "error_code":"INVALID_ENUM","message":f"status '{st}' not in allowed set {status_allowed}",
                               "severity":"High","autofix_suggestion":"Normalize to allowed values"})

        # registration_city
        if 'registration_city' in enabled_features:
            city = row.get('registration_city', None)
            if pd.isna(city) or str(city).strip()=="":
                issues.append({"row_index": idx, "application_number": app_no, "field":"registration_city",
                               "error_code":"MISSING","message":"registration_city missing","severity":"High","autofix_suggestion":"Manual review"})
            else:
                if str(city).strip() not in known_cities:
                    issues.append({"row_index": idx, "application_number": app_no, "field":"registration_city",
                                   "error_code":"UNKNOWN_CITY","message":f"registration_city '{city}' not in known list","severity":"High",
                                   "autofix_suggestion":"Fuzzy match or manual review"})

        # goods_services_description
        if 'goods_services_description' in enabled_features:
            gsd = row.get('goods_services_description', None)
            if pd.isna(gsd) or str(gsd).strip() == "":
                issues.append({"row_index": idx, "application_number": app_no, "field":"goods_services_description",
                               "error_code":"EMPTY","message":"goods_services_description empty","severity":"High","autofix_suggestion":"Check extraction"})

        # business_type_category
        if 'business_type_category' in enabled_features:
            btc = row.get('business_type_category', None)
            if pd.isna(btc) or str(btc).strip().lower() not in business_allowed:
                issues.append({"row_index": idx, "application_number": app_no, "field":"business_type_category",
                               "error_code":"INVALID_ENUM","message":f"business_type_category '{btc}' not in {business_allowed}",
                               "severity":"Medium","autofix_suggestion":"Derive from NICE class or manual"})

    issues_df = pd.DataFrame(issues)
    return issues_df

# -----------------------
# CLI and orchestration
# -----------------------
def main():
    p = argparse.ArgumentParser(description="Trademarks extraction audit script (checklist-driven)")
    p.add_argument("--data", required=True, help="Path to extracted data CSV")
    p.add_argument("--checklist", required=True, help="Path to checklist CSV (Feature, Validation Rules, Severity columns expected)")
    p.add_argument("--outdir", default=".", help="Output directory for reports")
    p.add_argument("--make-trimmed", action="store_true", help="Save a trimmed checklist CSV containing only Keep_Flag==True")
    p.add_argument("--force-all", action="store_true", help="Ignore Keep_Flag and run all checks from checklist")
    p.add_argument("--trim-defaults", action="store_true", help="Auto-populate Keep_Flag based on core defaults (recommended).")
    args = p.parse_args()

    data_path = args.data
    checklist_path = args.checklist
    outdir = args.outdir
    os.makedirs(outdir, exist_ok=True)

    # Load files
    data_df = pd.read_csv(data_path)
    checklist_df = pd.read_csv(checklist_path)

    # Normalize columns
    checklist_df.columns = checklist_df.columns.str.strip()
    data_df.columns = data_df.columns.str.strip()

    # Ensure Keep_Flag col exists; default True
    if 'Keep_Flag' not in checklist_df.columns or args.trim_defaults:
        # create or overwrite based on trim defaults
        def compute_keep(feature):
            if args.force_all:
                return True
            f = str(feature).strip().lower()
            # if trim_defaults: set True only for core flags mapping if available
            if args.trim_defaults:
                # if we know default flags for this feature, check if any of them intersects CORE_FLAGS
                defaults = FEATURE_TO_DEFAULT_FLAGS.get(f, [])
                # if any default error is in CORE_FLAGS => keep
                for d in defaults:
                    if d in CORE_FLAGS:
                        return True
                # otherwise don't keep by default
                return False
            else:
                return True

        # apply
        checklist_df['Keep_Flag'] = checklist_df['Feature'].apply(compute_keep)

    # Save updated checklist back (so user can edit Keep_Flag manually later)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    updated_checklist_path = os.path.join(outdir, f"checklist_updated_{ts}.csv")
    checklist_df.to_csv(updated_checklist_path, index=False)
    print(f"Updated checklist saved to: {updated_checklist_path}")

    # Optionally produce trimmed checklist with only Keep_Flag True
    if args.make_trimmed:
        trimmed = checklist_df[checklist_df['Keep_Flag'] == True].copy()
        trimmed_path = os.path.join(outdir, f"checklist_trimmed_{ts}.csv")
        trimmed.to_csv(trimmed_path, index=False)
        print(f"Trimmed checklist saved to: {trimmed_path}")

    # Run audit using enabled checks in checklist_df
    issues_df = run_audit(data_df, checklist_df, only_enabled=True, force_all=args.force_all)

    # Save issues report
    report_path = os.path.join(outdir, f"trademark_extraction_discrepancy_report_{ts}.csv")
    issues_df.to_csv(report_path, index=False)
    print(f"Discrepancy report written to: {report_path}")

    # Print summary
    total = len(data_df)
    issues_count = len(issues_df)
    print(f"Rows audited: {total}")
    print(f"Issues found: {issues_count}")
    if issues_count > 0:
        print("Top 10 issues by severity:")
        try:
            print(issues_df['severity'].value_counts().to_string())
            print("\nSample issues (first 10):")
            print(issues_df.head(10).to_string(index=False))
        except Exception:
            pass

if __name__ == "__main__":
    main()
