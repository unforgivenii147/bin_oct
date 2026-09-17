#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

import pdfplumber
from joblib import Parallel, delayed


def extract_single_page(page_data):
    page_num, pdf_path, output_dir = page_data
    if page_num % 10 == 0:
        print(f"processing page {page_num}")
    try:
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[page_num - 1]
            text = page.extract_text() or ""
        page_file = output_dir / f"page_{page_num:03d}.txt"
        page_file.write_text(text, encoding="utf-8")
        return page_num, page_file
    except Exception as e:
        print(f"Error extracting page {page_num}: {e}", file=sys.stderr)
        return None


def extract_pages_from_pdf(pdf_path, n_jobs=4):
    pdf_path = Path(pdf_path)
    output_dir = pdf_path.parent / pdf_path.stem
    output_dir.mkdir(exist_ok=True)
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
    pages_data = [
        (page_num, pdf_path, output_dir) for page_num in range(1, total_pages + 1)
    ]
    page_results = Parallel(n_jobs=n_jobs, backend="threading")(
        delayed(extract_single_page)(page_data) for page_data in pages_data
    )
    return [result for result in page_results if result is not None]


def collect_pdf_files(inputs):
    pdf_files = []
    if not inputs:
        inputs = [Path(".")]
    for item in inputs:
        path = Path(item)
        if path.is_file() and path.suffix.lower() == ".pdf":
            pdf_files.append(path)
        elif path.is_dir():
            pdf_files.extend(path.rglob("*.pdf"))
        else:
            print(
                f"Warning: {path} is not a valid PDF file or directory", file=sys.stderr
            )
    return pdf_files


def main():
    inputs = sys.argv[1:] if len(sys.argv) > 1 else []
    pdf_files = collect_pdf_files(inputs)
    if not pdf_files:
        print("No PDF files found.", file=sys.stderr)
        return
    print(f"Found {len(pdf_files)} PDF file(s) to process.")
    for i, pdf_file in enumerate(pdf_files, 1):
        print(f"Processing file {i}/{len(pdf_files)}: {pdf_file.name}")
        try:
            results = extract_pages_from_pdf(pdf_file, n_jobs=8)
            print(f"  Extracted {len(results)} pages from {pdf_file.name}")
        except Exception as e:
            print(f"Failed to process {pdf_file}: {e}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
