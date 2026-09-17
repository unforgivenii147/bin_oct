#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import pydoc
from pathlib import Path


def collect_files(root: Path, recursive: bool) -> list[Path]:
    paths = root.rglob("*") if recursive else root.iterdir()
    return sorted(
        (path for path in paths if path.is_file()),
        key=lambda path: str(path).lower(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="View files in the current directory with paging."
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="include files in subdirectories",
    )
    args = parser.parse_args()
    root = Path.cwd()
    files = collect_files(root, args.recursive)
    if not files:
        print("No files found.")
        return
    output = []
    for path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            content = f"[Could not read file: {exc}]"
        output.append(f"\n{'=' * 40}")
        output.append(f"FILE: {path.relative_to(root)}")
        output.append("=" * 40)
        output.append(content)
    pydoc.pager("\n".join(output))


if __name__ == "__main__":
    raise SystemExit(main())
