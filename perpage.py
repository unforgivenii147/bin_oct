#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import get_files, mpf_joblib
from PyPDF2 import PdfReader


def process_file(path) -> None:
    path = Path(path)
    if not path.is_file() or path.suffix.lower() != ".pdf":
        print(f"Error: Invalid PDF file path provided: {path}")
        return
    filename_base = path.stem
    output_folder = path.parent / filename_base
    try:
        output_folder.mkdir(parents=True, exist_ok=True)
        print(f"Saving page text files to: {output_folder}")
    except OSError as e:
        print(f"Error creating output directory {output_folder}: {e}")
        return
    try:
        reader = PdfReader(path)
    except Exception as e:
        print(f"Error opening PDF file {path}: {e}")
        return
    num_pages = len(reader.pages)
    padding = len(str(num_pages))
    print(f"Processing PDF: {path.name} ({num_pages} pages)")
    for page_num in range(num_pages):
        padded = str(page_num + 1).zfill(padding)
        page_filename = f"{filename_base}_{padded}.txt"
        output_path = output_folder / page_filename
        if output_path.exists():
            continue
        try:
            page = reader.pages[page_num]
            text = page.extract_text()
            if text:
                with output_path.open("w", encoding="utf-8") as txt_file:
                    txt_file.write(text)
                if page_num % 10 == 0:
                    print(f"Saved: {output_path.name}")
            else:
                print(f"Warning: No text extracted from page {page_num + 1}.")
        except Exception as e:
            print(f"Error processing page {page_num + 1}: {e}")


if __name__ == "__main__":
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_files(cwd, ext=[".pdf", ".PDF"])
    if len(files) == 1:
        process_file(files[0])
        sys.exit(0)
    mpf_joblib(process_file, files)
