from pathlib import Path
import argparse
from pipelines.pipeline_runner import CombinedPipeline
from pipelines.data_cleaner import DataCleaner

# Try to load environment variables from .env if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # python-dotenv not installed; continue without loading .env
    pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input_pdf', nargs='?', default=None, help='Path to input PDF or existing CSV if --from-csv')
    parser.add_argument('--from-csv', action='store_true')
    parser.add_argument('--pipeline', choices=['pipeline', 'pipeline_2'], default='pipeline')
    parser.add_argument('--out-dir', default='output')
    parser.add_argument('--output-prefix', default='main')
    parser.add_argument('--csv-name', default=None, help='Optional CSV file name (basename) produced by the pipeline to use for downstream steps')
    parser.add_argument('--default-pdf', default=None, help='Optional default PDF path to use if input_pdf is not provided')
    parser.add_argument('--auto-prefix-from-pdf', action='store_true', help='If set, derive output-prefix from the input PDF filename (without extension)')
    parser.add_argument('--pdf-dir', default=None, help='If set, process all PDFs in this directory (creates separate outputs per PDF)')
    parser.add_argument('--pipeline-map', default=None, help='Optional CSV mapping file with columns: pdf,pipeline to choose pipeline per-PDF')
    parser.add_argument('--no-postprocess', action='store_true', help='If set, skip chunk/extract/fill post-processing (useful for smoke tests)')
    parser.add_argument('--mock-extractor', action='store_true', help='If set, use a mocked extractor that generates fake trademark entries for each chunk')
    parser.add_argument('--timestamp-suffix', action='store_true', help='Append a timestamp to the output-prefix to avoid collisions for repeated runs')
    parser.add_argument('--tesseract-cmd', default=None, help='Optional path to tesseract executable to set for pytesseract (overrides TESSERACT_CMD env)')
    parser.add_argument('--list-pipelines', action='store_true', help='Dry-run: list which pipeline would be used for each PDF and exit')
    args = parser.parse_args()

    # Determine input PDF path: positional overrides default; if none provided and not coming from CSV, error.
    if args.input_pdf:
        input_path = Path(args.input_pdf)
    elif args.default_pdf:
        input_path = Path(args.default_pdf)
    else:
        input_path = None
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # If user supplied a directory of PDFs, gather them and process sequentially
    pdf_list = []
    if args.pdf_dir:
        pd_dir = Path(args.pdf_dir)
        if not pd_dir.exists() or not pd_dir.is_dir():
            parser.error(f"--pdf-dir specified but not a directory: {args.pdf_dir}")
        pdf_list = sorted([p for p in pd_dir.iterdir() if p.suffix.lower() in ['.pdf']])

    # Load pipeline mapping if provided
    pipeline_map = {}
    if args.pipeline_map:
        import csv
        map_path = Path(args.pipeline_map)
        if map_path.exists():
            with open(map_path, newline='', encoding='utf-8') as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    key = (row.get('pdf') or '').strip()
                    val = (row.get('pipeline') or '').strip()
                    if key and val:
                        pipeline_map[key] = val
        else:
            print(f"Warning: pipeline-map specified but file not found: {args.pipeline_map}")

    # If list-pipelines requested, do a pure dry-run and exit before running pipelines
    if args.list_pipelines:
        # If --pdf-dir, list for the dir; otherwise list for the single input/default
        if args.pdf_dir:
            pd_dir = Path(args.pdf_dir)
            pdf_list = sorted([p for p in pd_dir.iterdir() if p.suffix.lower() in ['.pdf']])
            for p in pdf_list:
                chosen = args.pipeline
                if p.name in pipeline_map:
                    chosen = pipeline_map[p.name]
                elif p.stem in pipeline_map:
                    chosen = pipeline_map[p.stem]
                print(f"{p.name} -> {chosen}")
        else:
            p = Path(args.input_pdf) if args.input_pdf else Path(args.default_pdf) if args.default_pdf else None
            if p is None:
                print("No PDF provided for dry-run.")
            else:
                chosen = args.pipeline
                if p.name in pipeline_map:
                    chosen = pipeline_map[p.name]
                elif p.stem in pipeline_map:
                    chosen = pipeline_map[p.stem]
                print(f"{p.name} -> {chosen}")
        return

    runner = CombinedPipeline()

    if args.from_csv:
        print(f"Starting from CSV: {input_path}")
        pipeline_csv = input_path
    else:
        if input_path is None and not pdf_list:
            parser.error("No input PDF provided, --default-pdf not set, and --pdf-dir not provided. Provide a PDF path or set --default-pdf or --pdf-dir.")

        # helper to run one PDF
        def run_single(pdf_path: Path):
            local_prefix = args.output_prefix
            if args.auto_prefix_from_pdf or local_prefix == 'main':
                local_prefix = pdf_path.stem
            if args.timestamp_suffix:
                from datetime import datetime
                ts = datetime.now().strftime('%Y%m%d-%H%M%S')
                local_prefix = f"{local_prefix}_{ts}"

            # Determine pipeline for this PDF (pipeline_map takes precedence)
            chosen_pipeline = args.pipeline
            stem = pdf_path.name
            if stem in pipeline_map:
                chosen_pipeline = pipeline_map[stem]
            elif pdf_path.stem in pipeline_map:
                chosen_pipeline = pipeline_map[pdf_path.stem]

            print(f"Running pipeline '{chosen_pipeline}' on {pdf_path} -> outputs in {out_dir} (prefix={local_prefix})")
            # Pass tesseract path through to pipelines so they can set pytesseract.pytesseract.tesseract_cmd
            tesseract_cmd = args.tesseract_cmd or None
            if chosen_pipeline == 'pipeline':
                produced = runner.pipeline(pdf_path, out_dir, output_tag=local_prefix, tesseract_cmd=tesseract_cmd)
            else:
                produced = runner.pipeline_2(pdf_path, out_dir, output_tag=local_prefix, tesseract_cmd=tesseract_cmd)

            # produced may be the out_dir or a Path to CSV/discovery location
            produced_path = Path(produced)
            pipeline_csv = None

            # primary location where pipeline writes: <out_dir>/outputs/<local_prefix>/csv
            csv_dir_primary = out_dir / 'outputs' / local_prefix / 'csv'
            csv_dir_secondary = out_dir / 'csv'

            # If user supplied csv-name, look in primary then secondary
            if args.csv_name:
                candidate = csv_dir_primary / args.csv_name
                if candidate.exists():
                    pipeline_csv = candidate
                else:
                    candidate2 = csv_dir_secondary / args.csv_name
                    if candidate2.exists():
                        pipeline_csv = candidate2
                    else:
                        print(f"Explicit csv-name provided but not found at {candidate} or {candidate2}")

            # If explicit not provided or not found, try the produced_path or primary/secondary discovery
            if pipeline_csv is None:
                if produced_path.is_file() and produced_path.suffix == '.csv':
                    pipeline_csv = produced_path
                else:
                    # Try primary dir first
                    cleaner = DataCleaner()
                    found = cleaner.find_input_csv(csv_dir_primary, csv_name=args.csv_name, prefix=local_prefix)
                    if found:
                        pipeline_csv = found
                    else:
                        # then try secondary dir
                        found2 = cleaner.find_input_csv(csv_dir_secondary, csv_name=args.csv_name, prefix=local_prefix)
                        if found2:
                            pipeline_csv = found2
                        else:
                            print(f"Could not locate pipeline CSV in expected locations for prefix {local_prefix}. Downstream cleaning will be skipped.")

            # If we have a CSV, run the cleaner
            if pipeline_csv and pipeline_csv.exists():
                cleaner = DataCleaner()
                cleaned_path = pipeline_csv.with_name(pipeline_csv.stem + '_cleaned.csv')
                try:
                    cleaner.clean(pipeline_csv, cleaned_path)
                    print(f"Cleaned CSV written to: {cleaned_path}")
                except Exception as e:
                    print(f"Data cleaning failed: {e}")
                # After cleaning, optionally run PDF chunking -> trademark extraction -> filler
                if getattr(args, 'no_postprocess', False):
                    print("Skipping post-processing steps (--no-postprocess set)")
                else:
                    try:
                        from pipelines.pdf_chunker import PDFChunker
                        from pipelines.trademark_extractor import TrademarkExtractor
                        from pipelines.trademark_filler import TrademarkFiller

                        chunks_dir = out_dir / 'outputs' / local_prefix / 'pdf_chunks'
                        # create chunker and run
                        chunker = PDFChunker()
                        chunk_files = chunker.chunk(pdf_path, out_dir)
                        print(f"Created {len(chunk_files)} chunk files in {chunks_dir}")

                        # run extractor to produce trademark CSV
                        trademark_csv = out_dir / 'outputs' / local_prefix / 'csv' / 'trademarks.csv'
                        extractor = TrademarkExtractor(api_key=None, mock=args.mock_extractor)
                        trademark_csv = extractor.extract(chunks_dir, trademark_csv)
                        print(f"Trademark CSV written to: {trademark_csv}")

                        # run filler to merge trademarks into cleaned CSV
                        filler = TrademarkFiller()
                        final_csv = out_dir / 'outputs' / local_prefix / 'csv' / (cleaned_path.stem + '_with_trademarks.csv')
                        final_csv = filler.fill(cleaned_path, trademark_csv, final_csv)
                        print(f"Final filled CSV written to: {final_csv}")
                        # run translation step to create final.csv
                        try:
                            from translation import translate_csv
                            translated = out_dir / 'outputs' / local_prefix / 'csv' / 'final.csv'
                            translate_csv(str(final_csv), str(translated))
                            print(f"Translated final CSV written to: {translated}")
                        except Exception as te:
                            print(f"Translation step failed: {te}")
                    except Exception as e:
                        print(f"Post-processing (chunk/extract/fill) failed: {e}")

        # If list-pipelines flag set, simply print which pipeline would be used and exit
        if args.list_pipelines:
            if pdf_list:
                for p in pdf_list:
                    chosen = args.pipeline
                    if p.name in pipeline_map:
                        chosen = pipeline_map[p.name]
                    elif p.stem in pipeline_map:
                        chosen = pipeline_map[p.stem]
                    print(f"{p.name} -> {chosen}")
            else:
                p = input_path
                chosen = args.pipeline
                if p.name in pipeline_map:
                    chosen = pipeline_map[p.name]
                elif p.stem in pipeline_map:
                    chosen = pipeline_map[p.stem]
                print(f"{p.name} -> {chosen}")
            return

        # run either single PDF or the list from pdf_dir
        if pdf_list:
            for p in pdf_list:
                run_single(p)
        else:
            run_single(input_path)
        


if __name__ == '__main__':
    main()
