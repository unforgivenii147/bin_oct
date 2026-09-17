#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.segment import Segment


def get_terminal_page_size(console: Console) -> int:
    size = shutil.get_terminal_size(fallback=(80, 24))
    return max(size.lines - 2, 5)


def render_markdown_to_lines(console: Console, markdown_text: str) -> list:
    md = Markdown(markdown_text)
    width = console.size.width
    segments = list(console.render(md, console.options.update(width=width)))
    lines = []
    current_line = []
    for segment in segments:
        text = segment.text
        if "\n" in text:
            parts = text.split("\n")
            for i, part in enumerate(parts):
                if part:
                    current_line.append(Segment(part, segment.style))
                if i != len(parts) - 1:
                    lines.append(current_line)
                    current_line = []
        else:
            current_line.append(segment)
    if current_line:
        lines.append(current_line)
    return lines


def paginate(console: Console, lines: list[str], page_size):
    total_lines = len(lines)
    total_pages = (total_lines + page_size - 1) // page_size if total_lines else 1
    current_page = 0
    while True:
        console.clear()
        start = current_page * page_size
        end = min(start + page_size, total_lines)
        for line_segments in lines[start:end]:
            console.print(*line_segments, end="")
            console.print()
        console.print()
        footer = f"[bold cyan]-- Page {current_page + 1}/{total_pages} -- [n] next  [p] prev  [q] quit --[/bold cyan]"
        console.print(footer)
        if current_page >= total_pages - 1 and total_pages == 1:
            key = input("Press [q] to quit: ").strip().lower()
            if key == "q" or key == "":
                break
            continue
        key = input("Command (n/p/q): ").strip().lower()
        if key in ("n", "next", ""):
            if current_page < total_pages - 1:
                current_page += 1
            else:
                console.print("[yellow]Already at the last page.[/yellow]")
        elif key in ("p", "prev", "previous"):
            if current_page > 0:
                current_page -= 1
            else:
                console.print("[yellow]Already at the first page.[/yellow]")
        elif key in ("q", "quit", "exit"):
            break
        else:
            console.print("[red]Unknown command. Use n, p, or q.[/red]")


def main():
    if len(sys.argv) != 2:
        print("Usage: python mdview.py <file.md>")
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Error: File '{path}' does not exist.")
        sys.exit(1)
    if not path.is_file():
        print(f"Error: '{path}' is not a file.")
        sys.exit(1)
    try:
        markdown_text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)
    console = Console()
    page_size = get_terminal_page_size(console)
    lines = render_markdown_to_lines(console, markdown_text)
    if not lines:
        console.print("[yellow]The file is empty.[/yellow]")
        sys.exit(0)
    paginate(console, lines, page_size)
    console.print("[green]Done.[/green]")


if __name__ == "__main__":
    main()
