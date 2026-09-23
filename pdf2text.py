#!/data/data/com.termux/files/home/.local/bin/python
"""
pdf_text_extractor.py

Merge of the original scripts:

    pdf2text.py  ->  python pdf_text_extractor.py concat input.pdf
    pdftotxt.py  ->  python pdf_text_extractor.py split input.pdf

Third-party dependencies used by the original scripts:

    PyPDF2
    pdfplumber

Install them with:

    pip install PyPDF2 pdfplumber

Usage examples:

    # Concatenate all pages into one text file, using PyPDF2 (original pdf2text.py behavior)
    python pdf_text_extractor.py concat input.pdf

    # Concatenate all pages into one text file, using pdfplumber
    python pdf_text_extractor.py concat input.pdf --engine pdfplumber -o output.txt

    # Split each page into its own text file, using pdfplumber (original pdftotxt.py behavior)
    python pdf_text_extractor.py split input.pdf

    # Split each page, choosing a different output directory and engine
    python pdf_text_extractor.py split input.pdf --output-dir out --engine pypdf2

    # Split each page, allowing nested output directories
    python pdf_text_extractor.py split input.pdf --output-dir out/book --parents
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterator, List, Optional


# ---------------------------------------------------------------------------
# Page extraction helpers
# ---------------------------------------------------------------------------


def _extract_pages_pypdf2(pdf_path: Path) -> Iterator[str]:
    """
    Yield extracted text for each page using PyPDF2.

    This mirrors the original pdf2text.py behavior:
        PyPDF2.PdfReader(...).pages[i].extract_text()

    PyPDF2's extract_text() does not take an encoding argument.
    """
    import PyPDF2

    with pdf_path.open("rb") as fh:
        reader = PyPDF2.PdfReader(fh)
        for page in reader.pages:
            text = page.extract_text()
            yield text or ""


def _extract_pages_pdfplumber(pdf_path: Path, encoding: str) -> Iterator[str]:
    """
    Yield extracted text for each page using pdfplumber.

    This mirrors the original pdftotxt.py behavior:
        pdfplumber.open(...).pages[i].extract_text(encoding='utf-8')

    Some pdfplumber versions accept an encoding keyword; older/newer versions
    may ignore it or reject it. We try the original call first and fall back
    to the no-encoding call only if the installed version raises TypeError.
    """
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            try:
                text = page.extract_text(encoding=encoding)
            except TypeError:
                text = page.extract_text()
            yield text or ""


def extract_pages(pdf_path: Path, engine: str, encoding: str) -> Iterator[str]:
    """
    Yield extracted text page by page using the selected PDF engine.

    Args:
        pdf_path: Path to the input PDF.
        engine: Either "pypdf2" or "pdfplumber".
        encoding: Text encoding passed to pdfplumber when supported.

    Yields:
        Extracted text for each page, in page order.
    """
    if engine == "pypdf2":
        yield from _extract_pages_pypdf2(pdf_path)
    elif engine == "pdfplumber":
        yield from _extract_pages_pdfplumber(pdf_path, encoding)
    else:
        raise ValueError(f"Unsupported engine: {engine}")


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def write_text(path: Path, text: str, encoding: str) -> None:
    """Write text to path using the given encoding."""
    path.write_text(text, encoding=encoding)


def default_concat_output(pdf_path: Path) -> Path:
    """
    Return the default concatenated output path.

    Original pdf2text.py did:
        f.replace('.pdf', '.txt')

    We preserve that behavior as closely as possible.
    """
    return Path(str(pdf_path).replace(".pdf", ".txt"))


def default_split_output_dir(pdf_path: Path) -> Path:
    """
    Return the default split output directory.

    Original pdftotxt.py used the PDF stem as the directory name, e.g.
        book.pdf -> book/
    """
    return Path(pdf_path.stem)


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def concat_text(
    pdf_path: Path,
    output: Optional[Path],
    engine: str,
    encoding: str,
    quiet: bool,
) -> int:
    """
    Concatenate all PDF pages into one text file.

    This is the original pdf2text.py behavior.
    """
    if output is None:
        output = default_concat_output(pdf_path)

    text = "".join(extract_pages(pdf_path, engine, encoding))
    write_text(output, text, encoding)

    if not quiet:
        print(f"Text extracted and saved to {output}")

    return 0


def split_text(
    pdf_path: Path,
    output_dir: Optional[Path],
    engine: str,
    encoding: str,
    pad_width: int,
    parents: bool,
    quiet: bool,
) -> int:
    """
    Split each PDF page into its own text file.

    This is the original pdftotxt.py behavior.

    Page numbering starts at 1. The default pad width is 3, so page 1 becomes
    "001", page 10 becomes "010", and page 100 becomes "100".
    """
    if pad_width < 1:
        raise ValueError("--pad-width must be at least 1")

    if output_dir is None:
        output_dir = default_split_output_dir(pdf_path)

    output_dir.mkdir(parents=parents, exist_ok=True)

    for page_number, text in enumerate(
        extract_pages(pdf_path, engine, encoding),
        start=1,
    ):
        page_str = f"{page_number:0{pad_width}d}"
        out_path = output_dir / f"{pdf_path.stem}{page_str}.txt"

        write_text(out_path, text, encoding)

        if not quiet:
            print(f"{out_path} created")

    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def run_concat(args: argparse.Namespace) -> int:
    """Dispatch function for the concat subcommand."""
    return concat_text(
        pdf_path=args.pdf,
        output=args.output,
        engine=args.engine,
        encoding=args.encoding,
        quiet=args.quiet,
    )


def run_split(args: argparse.Namespace) -> int:
    """Dispatch function for the split subcommand."""
    return split_text(
        pdf_path=args.pdf,
        output_dir=args.output_dir,
        engine=args.engine,
        encoding=args.encoding,
        pad_width=args.pad_width,
        parents=args.parents,
        quiet=args.quiet,
    )


def build_parser() -> argparse.ArgumentParser:
    """
    Build the CLI parser.

    Two subcommands are exposed:

        concat  -> original pdf2text.py behavior
        split   -> original pdftotxt.py behavior
    """
    parser = argparse.ArgumentParser(
        prog="pdf_text_extractor.py",
        description="Extract text from PDF files using PyPDF2 or pdfplumber.",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        help="Extraction mode",
    )

    # Common arguments shared by both subcommands.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "pdf",
        type=Path,
        help="Path to the input PDF file.",
    )
    common.add_argument(
        "--encoding",
        default="utf-8",
        help="Text encoding used when writing output files. Default: utf-8",
    )
    common.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress messages.",
    )
    common.add_argument(
        "--engine",
        choices=("pypdf2", "pdfplumber"),
        help=(
            "PDF extraction engine. Defaults: pypdf2 for concat, pdfplumber for split."
        ),
    )

    # concat subcommand: original pdf2text.py
    concat = subparsers.add_parser(
        "concat",
        parents=[common],
        help="Extract all pages into a single text file.",
    )
    concat.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=("Output .txt file. Default: input path with .pdf replaced by .txt."),
    )
    concat.set_defaults(func=run_concat, engine="pypdf2")

    # split subcommand: original pdftotxt.py
    split = subparsers.add_parser(
        "split",
        parents=[common],
        help="Extract each page into its own text file.",
    )
    split.add_argument(
        "-d",
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Directory for per-page text files. Default: directory named "
            "after the PDF stem."
        ),
    )
    split.add_argument(
        "--pad-width",
        type=int,
        default=3,
        help="Minimum page-number width. Default: 3 (001, 002, ...).",
    )
    split.add_argument(
        "--parents",
        action="store_true",
        help="Create parent directories for --output-dir if needed.",
    )
    split.set_defaults(func=run_split, engine="pdfplumber")

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    """
    Program entry point.

    Args:
        argv: Optional argument list. Defaults to sys.argv[1:].

    Returns:
        Exit status code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.pdf.is_file():
        parser.error(f"PDF file not found: {args.pdf}")

    try:
        return args.func(args)
    except ImportError as exc:
        print(
            f"Missing dependency: {exc}. Install with: pip install PyPDF2 pdfplumber",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
