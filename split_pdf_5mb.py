#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import io
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def split_pdf_by_size(pdf_path: Path, output_dir: Path, max_size_mb: int = 5) -> None:
    max_size_bytes = max_size_mb * 1024 * 1024
    reader = PdfReader(pdf_path)
    stem = pdf_path.stem
    current_writer = PdfWriter()
    current_buffer = io.BytesIO()
    file_count = 1
    for page in reader.pages:
        test_writer = PdfWriter()
        test_writer.add_page(page)
        test_buffer = io.BytesIO()
        test_writer.write(test_buffer)
        test_buffer.tell()
        current_writer.add_page(page)
        current_buffer = io.BytesIO()
        current_writer.write(current_buffer)
        current_size = current_buffer.tell()
        if current_size > max_size_bytes and len(current_writer.pages) > 1:
            current_writer.pages.pop()
            current_buffer = io.BytesIO()
            current_writer.write(current_buffer)
            output_path = output_dir / f"{stem}_{file_count}.pdf"
            with open(output_path, "wb") as f:
                f.write(current_buffer.getvalue())
            current_writer = PdfWriter()
            current_writer.add_page(page)
            file_count += 1
    if len(current_writer.pages) > 0:
        output_path = output_dir / f"{stem}_{file_count}.pdf"
        current_buffer = io.BytesIO()
        current_writer.write(current_buffer)
        with open(output_path, "wb") as f:
            f.write(current_buffer.getvalue())


def process_pdfs(input_paths=None, output_dir: Path | None = None) -> None:
    if output_dir is None:
        output_dir = Path.cwd() / "output"
    output_dir.mkdir(exist_ok=True)
    if input_paths is None or len(input_paths) == 0:
        pdf_files = list(Path.cwd().rglob("*.pdf"))
    else:
        pdf_files = []
        for path in input_paths:
            p = Path(path)
            if p.is_file() and p.suffix.lower() == ".pdf":
                pdf_files.append(p)
            elif p.is_dir():
                pdf_files.extend(p.rglob("*.pdf"))
    if not pdf_files:
        print("No PDF files found.")
        return
    with ThreadPoolExecutor() as executor:
        for pdf_file in pdf_files:
            executor.submit(split_pdf_by_size, pdf_file, output_dir)
    print(f"Processing complete. Output files in: {output_dir}")


if __name__ == "__main__":
    args = sys.argv[1:] if len(sys.argv) > 1 else None
    process_pdfs(input_paths=args)
