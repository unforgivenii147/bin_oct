#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def split_pdf_by_page(pdf_path: Path, output_dir: Path) -> None:
    reader = PdfReader(pdf_path)
    stem = pdf_path.stem
    total_pages = len(reader.pages)
    padding = len(str(total_pages))
    for page_num, page in enumerate(reader.pages, 1):
        writer = PdfWriter()
        writer.add_page(page)
        padded_num = str(page_num).zfill(padding)
        output_path = output_dir / f"{stem}_{padded_num}.pdf"
        with open(output_path, "wb") as f:
            writer.write(f)


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
            executor.submit(split_pdf_by_page, pdf_file, output_dir)
    print(f"Processing complete. Output files in: {output_dir}")


if __name__ == "__main__":
    args = sys.argv[1:] if len(sys.argv) > 1 else None
    process_pdfs(input_paths=args)
