#!/data/data/com.termux/files/home/.local/bin/python
import multiprocessing as mp
import sys
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:
    print("pypdf not installed. Install with: pip install pypdf")
    sys.exit(1)


CHUNK_SIZE = 10


def extract_chunk(args):
    pdf_path, start_page, end_page, output_dir, total_pages = args
    print(f"processing pages {start_page + 1}-{end_page}")

    padding = len(str(total_pages))
    results = []

    try:
        with open(pdf_path, "rb") as f:
            reader = PdfReader(f)
            for page_num in range(start_page, end_page):
                try:
                    text = reader.pages[page_num].extract_text() or ""
                except Exception as e:
                    text = ""

                filename = f"page_{page_num + 1:0{padding}d}.txt"
                output_file = output_dir / filename
                output_file.write_text(text, encoding="utf-8")
                results.append((page_num + 1, str(output_file), len(text)))
    except Exception as e:
        # If the whole chunk fails, report error for each page in it
        for page_num in range(start_page, end_page):
            results.append((page_num + 1, f"ERROR: {e}", 0))

    return results


def extract_pdf(pdf_path):
    pdf_path = Path(pdf_path).resolve()

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    output_dir = Path(pdf_path.stem)
    output_dir.mkdir(exist_ok=True)

    with open(pdf_path, "rb") as f:
        reader = PdfReader(f)
        total_pages = len(reader.pages)

    print(f"PDF: {pdf_path.name}")
    print(f"Pages: {total_pages}")
    print(f"Output: {output_dir.resolve()}")

    # Build chunks of CHUNK_SIZE pages each
    tasks = []
    for start in range(0, total_pages, CHUNK_SIZE):
        end = min(start + CHUNK_SIZE, total_pages)
        tasks.append((str(pdf_path), start, end, output_dir, total_pages))

    print(f"Chunks: {len(tasks)} ({CHUNK_SIZE} pages each)")

    with mp.Pool(processes=8) as pool:
        for chunk_result in pool.imap_unordered(extract_chunk, tasks):
            for page_num, info, length in chunk_result:
                print(f"  Page {page_num}: {info} ({length} chars)")

    print("Done.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_pdf.py <pdf_file>")
        sys.exit(1)

    extract_pdf(sys.argv[1])
