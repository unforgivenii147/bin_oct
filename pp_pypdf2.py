#!/data/data/com.termux/files/home/.local/bin/python
import multiprocessing as mp
import sys
from pathlib import Path

try:
    import PyPDF2
except ImportError:
    print("PyPDF2 not installed. Install with: pip install PyPDF2")
    sys.exit(1)


def extract_page_text(args):
    pdf_path, page_num, output_dir, total_pages = args
    if page_num % 10 == 0:
        print(f"processing page {page_num}")
    try:
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            text = reader.pages[page_num].extract_text() or ""

        padding = len(str(total_pages))
        filename = f"page_{page_num + 1:0{padding}d}.txt"
        output_file = output_dir / filename

        output_file.write_text(text, encoding="utf-8")
        return (page_num + 1, str(output_file), len(text))
    except Exception as e:
        return (page_num + 1, f"ERROR: {e}", 0)


def extract_pdf(pdf_path):
    pdf_path = Path(pdf_path).resolve()

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    output_dir = Path(pdf_path.stem)
    output_dir.mkdir(exist_ok=True)

    with open(pdf_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        total_pages = len(reader.pages)

    print(f"PDF: {pdf_path.name}")
    print(f"Pages: {total_pages}")
    print(f"Output: {output_dir.resolve()}")

    tasks = [(str(pdf_path), i, output_dir, total_pages) for i in range(total_pages)]

    with mp.Pool(processes=8) as pool:
        results = [pool.apply_async(extract_page_text, (task,)) for task in tasks]

        for r in results:
            page_num, info, length = r.get()
            print(f"  Page {page_num}: {info} ({length} chars)")

    print("Done.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_pdf.py <pdf_file>")
        sys.exit(1)

    extract_pdf(sys.argv[1])
