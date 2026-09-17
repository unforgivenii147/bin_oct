#!/data/data/com.termux/files/home/.local/bin/python
import multiprocessing as mp
import sys
from pathlib import Path

try:
    from pdfminer.high_level import extract_text
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser
except ImportError:
    print("pdfminer.six not installed. Install with: pip install pdfminer.six")
    sys.exit(1)


def get_total_pages(pdf_path):
    """Count pages without loading whole doc into memory."""
    with open(pdf_path, "rb") as f:
        parser = PDFParser(f)
        doc = PDFDocument(parser)
        return sum(1 for _ in PDFPage.create_pages(doc))


def extract_page_range(args):
    pdf_path, page_nums, output_dir, total_pages = args
    padding = len(str(total_pages))
    results = []
    # Single parse, multiple pages
    for page_num in page_nums:
        try:
            text = extract_text(pdf_path, page_numbers=[page_num]) or ""
            filename = f"page_{page_num + 1:0{padding}d}.txt"
            output_file = output_dir / filename
            output_file.write_text(text, encoding="utf-8")
            results.append((page_num + 1, str(output_file), len(text)))
        except Exception as e:
            results.append((page_num + 1, f"ERROR: {e}", 0))
    return results


def extract_pdf(pdf_path, n_workers=8):
    pdf_path = Path(pdf_path).resolve()

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    output_dir = Path(pdf_path.stem)
    output_dir.mkdir(exist_ok=True)

    total_pages = get_total_pages(str(pdf_path))
    print(f"PDF: {pdf_path.name}\nPages: {total_pages}\nOutput: {output_dir.resolve()}")

    # Split into chunks
    chunk_size = max(1, total_pages // n_workers + 1)
    chunks = [
        list(range(i, min(i + chunk_size, total_pages)))
        for i in range(0, total_pages, chunk_size)
    ]

    tasks = [(str(pdf_path), chunk, output_dir, total_pages) for chunk in chunks]

    with mp.Pool(processes=n_workers) as pool:
        for chunk_results in pool.imap_unordered(extract_page_range, tasks):
            for page_num, info, length in chunk_results:
                print(f"  Page {page_num}: {info} ({length} chars)")

    print("Done.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_pdf.py <pdf_file> [n_workers]")
        sys.exit(1)

    pdf_file = sys.argv[1]
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    extract_pdf(pdf_file, n_workers=workers)
