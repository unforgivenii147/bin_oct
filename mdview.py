#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text


def read_markdown(path: str) -> str:
    path = Path(path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    return path.read_text(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mdview",
        description="View a Markdown file in the terminal, page by page.",
    )
    parser.add_argument(
        "file",
        type=str,
        help="Path to a Markdown file",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    console = Console()
    try:
        markdown_text = read_markdown(args.file)
    except FileNotFoundError as error:
        console.print(f"[red]Error:[/red] {error}", file=sys.stderr)
        return 1
    except PermissionError:
        console.print(
            f"[red]Error:[/red] Permission denied: {args.file}",
            file=sys.stderr,
        )
        return 1
    except UnicodeDecodeError:
        console.print(
            f"[red]Error:[/red] {args.file} is not a valid UTF-8 text file.",
            file=sys.stderr,
        )
        return 1
    except OSError as error:
        console.print(f"[red]Error:[/red] {error}", file=sys.stderr)
        return 1
    md = Markdown(markdown_text)
    segments = list(console.render(md, console.options))
    full_text = Text()
    for seg in segments:
        if isinstance(seg, Text):
            full_text.append(seg)
        else:
            full_text.append(Text(str(seg)))
    lines = full_text.split("\n")
    height = console.height - 1
    page_count = (len(lines) + height - 1) // height or 1
    current_page = 0
    while True:
        console.clear()
        start = current_page * height
        end = start + height
        page_lines = lines[start:end]
        page_text = Text()
        for i, line in enumerate(page_lines):
            page_text.append(line)
            if i != len(page_lines) - 1:
                page_text.append("\n")
        console.print(page_text)
        help_text = (
            f"[dim]Page {current_page + 1}/{page_count} | "
            "PgUp/PgDown or ↑/↓ to scroll | q to quit[/dim]"
        )
        console.print(help_text)
        try:
            key = console.input("")
        except EOFError:
            break
        if key in ("q", "Q"):
            break
        elif key == "":
            current_page = min(current_page + 1, page_count - 1)
        elif key in ("\x1b[A", "k"):
            current_page = max(current_page - 1, 0)
        elif key in ("\x1b[B", "j"):
            current_page = min(current_page + 1, page_count - 1)
        elif key == "\x1b[6~":
            current_page = min(current_page + 1, page_count - 1)
        elif key == "\x1b[5~":
            current_page = max(current_page - 1, 0)
        else:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
