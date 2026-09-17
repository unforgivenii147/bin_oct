#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def send_to_process(txt: str) -> None:
    try:
        process = subprocess.Popen(
            ["termux-clipboard-set"],
            stdin=subprocess.PIPE,
            text=True,
            stderr=subprocess.PIPE,
        )
        _stdout, stderr = process.communicate(input=txt)
        if process.returncode != 0:
            print(
                f"Error: Failed to copy to clipboard. STDERR: {stderr}", file=sys.stderr
            )
            sys.exit(1)
    except FileNotFoundError:
        print(
            "Error: 'termux-clipboard-set' command not found. Is Termux:API installed?",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        print(
            f"An unexpected error occurred while copying to clipboard: {e}",
            file=sys.stderr,
        )
        sys.exit(1)


def selective_copy(path: Path, lines: list[str]) -> None:
    cl = [p for p in lines if p != "-s"]
    selected = []
    nl = path.read_text(encoding="utf-8").splitlines()
    total = len(nl)
    for k in cl:
        if 0 <= k <= total:
            selected.append(nl[k])
    content = "".join(selected)
    send_to_process(content)


def copy_lines_to_clipboard(
    path: str | Path, start_line: int | None = None, end_line: int | None = None
) -> None:
    content = ""
    path = Path(path)
    if not path.is_file():
        print(f"Error: File not found at '{path}'", file=sys.stderr)
        sys.exit(1)
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as e:
        print(f"Error reading file '{path}': {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"error occurred while reading the file: {e}", file=sys.stderr)
        sys.exit(1)
    total_lines = len(lines)
    if start_line is None:
        content = "".join(lines)
    else:
        start_index = start_line - 1
        end_index = total_lines if end_line is None else end_line
        if not 0 <= start_index <= total_lines:
            start_index = 0
        if not 0 <= end_index <= total_lines:
            end_index = total_lines
        if start_index >= end_index:
            start_index, end_index = end_index, start_index
        selected_lines = lines[start_index:end_index]
        content = "".join(selected_lines)
    if not content:
        print("No content selected to copy.", file=sys.stderr)
        sys.exit(1)
    send_to_process(content)


def main() -> None:
    if len(sys.argv) < 2 or len(sys.argv) > 5:
        print(f"Usage: {sys.argv[0]} <path> [start_line] [end_line]", file=sys.stderr)
        print("  <path>: Path to the input file.", file=sys.stderr)
        print(
            "  [start_line]: The first line number to copy (1-based index). If omitted, copies the entire file.",
            file=sys.stderr,
        )
        print(
            "  [end_line]: The last line number to copy (1-based index). If omitted and start_line is given, copies to the end of the file.",
            file=sys.stderr,
        )
        sys.exit(1)
    selective = "-s" in sys.argv[1:]
    path = Path(sys.argv[1])
    start_line = None
    end_line = None
    if len(sys.argv) >= 3:
        try:
            start_line = int(sys.argv[2])
        except ValueError:
            print("Error: <start_line> must be an integer.", file=sys.stderr)
            sys.exit(1)
    if len(sys.argv) == 4:
        try:
            end_line = int(sys.argv[3])
        except ValueError:
            print("Error: <end_line> must be an integer.", file=sys.stderr)
            sys.exit(1)
    if start_line is not None and end_line is None and len(sys.argv) == 3:
        if not path.is_file():
            print(f"Error: File not found at '{path}'", file=sys.stderr)
            sys.exit(1)
        try:
            with path.open("r", encoding="utf-8") as f:
                total_lines = len(f.readlines())
            if not 1 <= start_line <= total_lines:
                print(
                    f"Error: Start line ({start_line}) is out of bounds. File has {total_lines} lines.",
                    file=sys.stderr,
                )
                sys.exit(1)
        except OSError as e:
            print(f"Error reading file '{path}' for validation: {e}", file=sys.stderr)
            sys.exit(1)
    if not selective:
        copy_lines_to_clipboard(path, start_line, end_line)
    else:
        selective_copy(path, sys.argv[2:])


if __name__ == "__main__":
    raise SystemExit(main())
