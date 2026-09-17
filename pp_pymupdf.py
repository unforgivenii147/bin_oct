#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

import fitz
from joblib import Parallel, delayed


def extract_page_batch(pdf_path, page_numbers, output_dir):
    results = []
    try:
        doc = fitz.open(pdf_path)
        for page_num in page_numbers:
            if page_num % 10 == 0:
                print(f"processing page {page_num}")
            page = doc[page_num - 1]
            text = page.get_text("text", sort=True)
            page_file = output_dir / f"page_{page_num:03d}.txt"
            page_file.write_text(text, encoding="utf-8")
            results.append((page_num, page_file))
        doc.close()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
    return results


def extract_pages_from_pdf(pdf_path, n_jobs=4):
    pdf_path = Path(pdf_path)
    output_dir = pdf_path.parent / pdf_path.stem
    output_dir.mkdir(exist_ok=True)
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        doc.close()
        batch_size = max(1, total_pages // n_jobs)
        batches = []
        for i in range(0, total_pages, batch_size):
            end = min(i + batch_size, total_pages)
            batches.append(list(range(i + 1, end + 1)))
        all_results = Parallel(n_jobs=n_jobs, backend="threading")(
            delayed(extract_page_batch)(pdf_path, batch, output_dir)
            for batch in batches
        )
        results = [item for sublist in all_results for item in sublist]
        return results
    except Exception as e:
        print(f"Error processing {pdf_path}: {e}", file=sys.stderr)
        return []


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
