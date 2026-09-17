#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path


def get_python_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def read_lines(path: Path) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f]
    except Exception as e:
        print(f"Warning: Could not read {path}: {e}", file=sys.stderr)
        return []


def is_skip_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#!"):
        return True
    return bool(stripped.startswith(("import ", "from ")))


def get_clean_lines(lines: list[str]) -> set[str]:
    return {line for line in lines if not is_skip_line(line)}


def analyze_files(
    files: list[Path], threshold: float, low_var_limit: int, freq_limit: int
) -> dict:
    pass


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze Python files for duplication."
    )
    parser.add_argument(
        "-t",
        "--threshold",
        type=float,
        default=85,
        help="Threshold % for common lines (default: 85)",
    )
    parser.add_argument(
        "-l",
        "--low-variance",
        type=int,
        default=20,
        help="Limit for low-variance files (default: 20)",
    )
    parser.add_argument(
        "-f",
        "--frequency",
        type=int,
        default=100,
        help="Frequency limit for repeated lines (default: 100)",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Directory to analyze (default: current directory)",
    )
    args = parser.parse_args()
    path = Path(args.path)
    if not path.is_dir():
        print(f"Error: {path} is not a directory", file=sys.stderr)
        sys.exit(1)
    files = get_python_files(path)
    if not files:
        print("No Python files found.", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(files)} Python files. Analyzing...", file=sys.stderr)
    results = analyze_files(
        files,
        threshold=args.threshold / 100,
        low_var_limit=args.low_variance,
        freq_limit=args.frequency,
    )


if __name__ == "__main__":
    raise SystemExit(main())
