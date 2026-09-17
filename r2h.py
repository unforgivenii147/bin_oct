#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import get_files, mpf_async
from docutils.core import publish_parts

MAX_WORKERS = 4


def rst_to_html(content: str) -> str:
    try:
        parts = publish_parts(
            source=content,
            writer_name="html",
            settings_overrides={
                "initial_header_level": 2,
                "warning_stream": None,
                "report_level": 5,
            },
        )
        html_content = parts["html_body"]
        return html_content
    except Exception as e:
        print(f"Conversion error details: {e}")
        raise


def process_file(path):
    path = Path(path)
    content = path.read_text(encoding="utf-8")
    html_content = rst_to_html(content)
    html_path = path.with_suffix(".html")
    html_path.write_text(html_content, encoding="utf-8")
    path.unlink()


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_files(cwd, ext=[".rst"])
    if len(files) == 1:
        process_file(files[0])
        sys.exit(1)
    mpf_async(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
