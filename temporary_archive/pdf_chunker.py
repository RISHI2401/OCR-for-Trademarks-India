from pathlib import Path
from typing import List
from PyPDF2 import PdfReader, PdfWriter

class PDFChunker:
    """
    Splits a PDF into smaller chunks and saves them to a structured output directory.
    """
    def __init__(self, chunk_size: int = 100, merge_threshold: int = 50):
        """
        Initializes the chunker with configuration.

        Args:
            chunk_size (int): The maximum number of pages per chunk.
            merge_threshold (int): If the last chunk has this many pages or fewer,
                                 it will be merged with the second-to-last chunk.
        """
        self.chunk_size = chunk_size
        self.merge_threshold = merge_threshold

    def chunk(self, pdf_path: Path, out_root: Path) -> List[Path]:
        """
        Chunks the given PDF file.

        Args:
            pdf_path (Path): The path to the source PDF file.
            out_root (Path): The root directory for all outputs. The chunks will be
                           saved in a subdirectory based on the PDF's name.

        Returns:
            List[Path]: A list of paths to the newly created PDF chunk files.
        """
        if not pdf_path.exists():
            raise FileNotFoundError(f"Source PDF not found at '{pdf_path}'")

        # Determine the specific output directory for this PDF's chunks
        chunks_dir = out_root / 'outputs' / pdf_path.stem / 'pdf_chunks'
        chunks_dir.mkdir(parents=True, exist_ok=True)
        print(f"Saving chunks to: '{chunks_dir}'")

        try:
            pdf_reader = PdfReader(pdf_path)
            total_pages = len(pdf_reader.pages)
            print(f"Source PDF '{pdf_path.name}' has {total_pages} pages.")

            if total_pages == 0:
                print("The PDF has no pages to chunk.")
                return []

            created_files: List[Path] = []
            num_full_chunks = total_pages // self.chunk_size
            remaining_pages = total_pages % self.chunk_size

            # Loop through the document and create full-sized chunks
            for i in range(num_full_chunks):
                pdf_writer = PdfWriter()
                start_page = i * self.chunk_size
                end_page = start_page + self.chunk_size

                # If this is the last full chunk and the remainder is small, merge it.
                if i == num_full_chunks - 1 and 0 < remaining_pages <= self.merge_threshold:
                    end_page = total_pages  # Extend to the end of the document
                
                for page_num in range(start_page, end_page):
                    pdf_writer.add_page(pdf_reader.pages[page_num])

                output_path = chunks_dir / f"{pdf_path.stem}_chunk_{i+1}_pages_{start_page+1}-{end_page}.pdf"
                with open(output_path, 'wb') as out_pdf:
                    pdf_writer.write(out_pdf)
                
                created_files.append(output_path)
                print(f"  -> Created chunk {i+1}: '{output_path.name}'")

            # Handle the final chunk if it was larger than the merge threshold
            if remaining_pages > self.merge_threshold:
                pdf_writer = PdfWriter()
                start_page = num_full_chunks * self.chunk_size
                end_page = total_pages

                for page_num in range(start_page, end_page):
                    pdf_writer.add_page(pdf_reader.pages[page_num])

                chunk_num = num_full_chunks + 1
                output_path = chunks_dir / f"{pdf_path.stem}_chunk_{chunk_num}_pages_{start_page+1}-{end_page}.pdf"
                with open(output_path, 'wb') as out_pdf:
                    pdf_writer.write(out_pdf)
                
                created_files.append(output_path)
                print(f"  -> Created final chunk {chunk_num}: '{output_path.name}'")

            print("\nPDF chunking complete!")
            return created_files

        except Exception as e:
            print(f"An unexpected error occurred during chunking: {e}")
            # Re-raise the exception to notify the main pipeline of the failure
            raise
