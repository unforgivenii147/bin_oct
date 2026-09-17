#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
from pathlib import Path

from weasyprint import HTML
from pdf2image import convert_from_bytes
from PIL import Image


# Fixed number of worker processes for the multiprocessing pool.
WORKERS = 8


def html_to_png(html_content: str | Path, output_path: Path, dpi: int = 150) -> Path:
    """
    Render an HTML document (from a string or a file path) to a single PNG image.

    Args:
        html_content: Either a raw HTML string (starting with '<') or a
                      filesystem path to an .html file.
        output_path:  Destination path for the generated PNG file.
        dpi:          Resolution used when rasterizing the PDF (dots per inch).

    Returns:
        The path where the PNG was written.
    """
    html_content = str(html_content)

    # Detect whether we received raw HTML markup or a path to an HTML file
    if html_content.startswith(("<", "<!DOCTYPE")):
        html = HTML(string=html_content)
    else:
        html = HTML(filename=html_content)

    # Render the HTML to a PDF in memory (bytes)
    pdf_bytes = html.write_pdf()

    # Convert the PDF bytes into a list of PIL images (one per PDF page)
    images = convert_from_bytes(pdf_bytes, dpi=dpi)

    # Ensure the parent directory exists before saving
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # If the HTML produced multiple PDF pages, stack them vertically
    if len(images) > 1:
        total_height = sum(img.height for img in images)
        max_width = max(img.width for img in images)
        combined = Image.new("RGB", (max_width, total_height), (255, 255, 255))
        y_offset = 0
        for img in images:
            combined.paste(img, (0, y_offset))
            y_offset += img.height
        combined.save(output_path, "PNG")
    else:
        # Only one page: save it directly
        images[0].save(output_path, "PNG")

    return output_path


def _convert_one(html_file: Path) -> Path:
    """
    Worker function used by the multiprocessing pool.

    Converts a single HTML file to a PNG placed next to it, using the same
    stem with a `.png` suffix.
    """
    output_path = html_file.with_suffix(".png")
    return html_to_png(html_file, output_path)


def collect_html_files(inputs: list[str]) -> list[Path]:
    """
    Expand the CLI inputs into a deduplicated list of .html files.

    - Each path in `inputs` may be a file or a directory.
    - Directories are walked recursively (`rglob`).
    - If `inputs` is empty, the current directory is walked recursively.
    """
    # No inputs provided -> process the current directory recursively
    if not inputs:
        inputs = ["."]

    found: list[Path] = []
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            # Recursively find every .html file under this directory
            found.extend(sorted(p.rglob("*.html")))
        elif p.is_file():
            # Accept any explicitly given file regardless of extension
            found.append(p)
        else:
            print(f"warning: skipping non-existent path: {p}", file=sys.stderr)

    # Deduplicate while preserving order
    seen: set[Path] = set()
    unique: list[Path] = []
    for f in found:
        rf = f.resolve()
        if rf not in seen:
            seen.add(rf)
            unique.append(f)
    return unique


def main() -> int:
    """Parse CLI arguments and convert all matching HTML files in parallel."""
    parser = argparse.ArgumentParser(
        description=(
            "Convert HTML files to PNG. Accepts one or more files or "
            "directories. With no arguments, walks the current directory "
            "recursively."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Files or directories to process (default: current directory).",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="Rasterization resolution in dots per inch (default: 150).",
    )
    args = parser.parse_args()

    html_files = collect_html_files(args.inputs)
    if not html_files:
        print("No HTML files found.", file=sys.stderr)
        return 1

    print(f"Converting {len(html_files)} file(s) with {WORKERS} workers...")

    # Fixed pool of 8 workers; results are processed as they complete.
    with mp.Pool(processes=WORKERS) as pool:
        # imap_unordered yields results in completion order, which is the
        # fastest way to consume them when order doesn't matter.
        for result in pool.imap_unordered(_convert_one, html_files):
            print(f"Saved: {result}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
