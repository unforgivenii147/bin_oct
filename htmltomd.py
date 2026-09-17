#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import sys
from multiprocessing import cpu_count
from pathlib import Path

from bs4 import BeautifulSoup
from html_to_markdown import Options, convert


def clean_html(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")
    for script in soup.find_all("script"):
        script.decompose()
    for style in soup.find_all("style"):
        style.decompose()
    for comment in soup.find_all(
        string=lambda text: isinstance(text, str) and text.strip().startswith("<!--")
    ):
        comment.extract()
    for tag in soup.find_all(["nav", "footer", "aside", "iframe", "noscript"]):
        tag.decompose()
    for form in soup.find_all("form"):
        form.decompose()
    return str(soup)


def convert_html_to_md(
    html_file: Path, options: Options | None = None
) -> tuple[Path, bool]:
    if html_file.suffix.lower() not in {".html", ".htm"}:
        print(f"Warning: {html_file} doesn't have .html/.htm extension, skipping.")
        return html_file, False
    try:
        html_content = html_file.read_text(encoding="utf-8")
        cleaned_html = clean_html(html_content)
        if options is None:
            options = Options(
                extract_headers=True,
                extract_links=True,
                extract_images=True,
                extract_structured_data=False,
                github_flavored=True,
            )
        markdown_content = convert(cleaned_html, options=options)
        markdown_content = "\n".join(
            line for line in markdown_content.split("\n") if line.strip() or line == ""
        )
        import re

        markdown_content = re.sub(r"\n{3,}", "\n\n", markdown_content)
        md_file = html_file.with_suffix(".md")
        md_file.write_text(markdown_content, encoding="utf-8")
        print(f"✓ Converted: {html_file.name} -> {md_file.name}")
        return md_file, True
    except Exception as e:
        print(f"✗ Error converting {html_file.name}: {e}", file=sys.stderr)
        return html_file, False


def find_html_files(directory: Path, recursive: bool = True) -> list[Path]:
    if recursive:
        html_files = list(directory.rglob("*.html")) + list(directory.rglob("*.htm"))
    else:
        html_files = list(directory.glob("*.html")) + list(directory.glob("*.htm"))
    return sorted(html_files)


def process_file_wrapper(args: tuple) -> tuple[Path, bool]:
    html_file, options = args
    return convert_html_to_md(html_file, options)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enhanced HTML to Markdown converter with better HTML5/JS/form handling",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s -r
  %(prog)s file.html
  %(prog)s /path/to/directory
  %(prog)s --no-recursive
        """,
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="HTML file or directory to process (default: current directory)",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        default=True,
        help="Process directories recursively (default: True)",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_false",
        dest="recursive",
        help="Disable recursive processing",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=cpu_count(),
        help=f"Number of worker processes (default: {cpu_count()})",
    )
    parser.add_argument(
        "--keep-forms",
        action="store_true",
        help="Keep form elements (default: remove them)",
    )
    parser.add_argument(
        "--github-flavored",
        action="store_true",
        default=True,
        help="Use GitHub-flavored Markdown (default: True)",
    )
    args = parser.parse_args()
    options = Options(
        extract_headers=True,
        extract_links=True,
        extract_images=True,
        extract_structured_data=False,
        github_flavored=args.github_flavored,
    )
    input_path = Path(args.path).resolve()
    if not input_path.exists():
        print(f"Error: Path '{input_path}' does not exist.", file=sys.stderr)
        sys.exit(1)
    if input_path.is_file():
        html_files = [input_path]
    elif input_path.is_dir():
        html_files = find_html_files(input_path, args.recursive)
        if not html_files:
            print(f"No HTML files found in {input_path}")
            sys.exit(0)
        print(f"Found {len(html_files)} HTML file(s) to process")
    else:
        print(
            f"Error: '{input_path}' is neither a file nor a directory.", file=sys.stderr
        )
        sys.exit(1)
    if len(html_files) == 1:
        convert_html_to_md(html_files[0], options)
    else:
        print(f"Using {args.workers} worker process(es)")
        process_args = [(f, options) for f in html_files]
        with Pool(processes=args.workers) as pool:
            results = pool.map(process_file_wrapper, process_args)
        successful = sum(1 for _, success in results if success)
        print(f"\n{'=' * 40}")
        print(
            f"Conversion complete: {successful}/{len(html_files)} files converted successfully"
        )


if __name__ == "__main__":
    raise SystemExit(main())
