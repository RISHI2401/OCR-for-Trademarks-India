from pathlib import Path
from typing import List
import os
import glob

# We'll reuse the existing top-level chunk_pdf() function if available;
# otherwise implement a simple fallback that uses PyPDF2.
try:
    from ..pdf_chunker import chunk_pdf as _orig_chunk_pdf
except Exception:
    _orig_chunk_pdf = None


class PDFChunker:
    def __init__(self, chunk_size: int = 100, merge_threshold: int = 50):
        self.chunk_size = chunk_size
        self.merge_threshold = merge_threshold

    def chunk(self, pdf_path: Path, out_root: Path) -> List[Path]:
        """Create a pdf_chunks folder under out_root/outputs/<prefix>/pdf_chunks and
        chunk the PDF there. Returns list of chunk file paths.
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        out_root = Path(out_root)
        chunks_dir = out_root / 'outputs' / pdf_path.stem / 'pdf_chunks'
        chunks_dir.mkdir(parents=True, exist_ok=True)

        # Use existing implementation when possible
        if _orig_chunk_pdf:
            _orig_chunk_pdf(str(pdf_path), str(chunks_dir), chunk_size=self.chunk_size, merge_threshold=self.merge_threshold)
        else:
            # fallback: call a simple chunking via PyPDF2 here if needed
            try:
                from PyPDF2 import PdfReader, PdfWriter
                reader = PdfReader(str(pdf_path))
                total_pages = len(reader.pages)
                if total_pages == 0:
                    return []

                created = []

                # If the PDF is smaller than or equal to chunk_size, create one chunk containing all pages
                if total_pages <= self.chunk_size:
                    writer = PdfWriter()
                    for pnum in range(0, total_pages):
                        writer.add_page(reader.pages[pnum])
                    outp = chunks_dir / f"{pdf_path.stem}_chunk_1_pages_1-{total_pages}.pdf"
                    with open(outp, 'wb') as f:
                        writer.write(f)
                    created.append(outp)
                else:
                    num_full_chunks = total_pages // self.chunk_size
                    remaining = total_pages % self.chunk_size
                    for i in range(num_full_chunks):
                        writer = PdfWriter()
                        start = i * self.chunk_size
                        end = start + self.chunk_size
                        # If this is the last full chunk and remainder is small, extend to the end
                        if i == num_full_chunks - 1 and 0 < remaining <= self.merge_threshold:
                            end = total_pages
                        for pnum in range(start, end):
                            writer.add_page(reader.pages[pnum])
                        outp = chunks_dir / f"{pdf_path.stem}_chunk_{i+1}_pages_{start+1}-{end}.pdf"
                        with open(outp, 'wb') as f:
                            writer.write(f)
                        created.append(outp)
                    if remaining > self.merge_threshold:
                        writer = PdfWriter()
                        start = num_full_chunks * self.chunk_size
                        for pnum in range(start, total_pages):
                            writer.add_page(reader.pages[pnum])
                        outp = chunks_dir / f"{pdf_path.stem}_chunk_{num_full_chunks+1}_pages_{start+1}-{total_pages}.pdf"
                        with open(outp, 'wb') as f:
                            writer.write(f)
                        created.append(outp)
            except Exception as e:
                raise RuntimeError(f"PDF chunking failed (no helper available): {e}")

        # Gather created chunk files (sorted)
        pattern = str(chunks_dir / f"{pdf_path.stem}_chunk_*.pdf")
        files = sorted([Path(p) for p in glob.glob(pattern)])
        return files
