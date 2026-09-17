#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a script that scans a directory tree for text files, detects non-English
lines using gcld3, and writes a report. It walks files with pathlib, filters by a
set of text-file extensions, processes files in parallel using a fixed
multiprocessing.Pool of 8 workers via apply_async, logs progress with loguru, and
writes findings and errors to an output report file.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

import gcld3

# Module-level detector instance. Created once per worker process.
_DETECTOR: gcld3.NNetLanguageIdentifier | None = None

TEXT_EXTENSIONS: set[str] = {
    ".txt",
    ".csv",
    ".log",
    ".md",
    ".rst",
    ".py",
    ".js",
    ".html",
    ".css",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".conf",
    ".sh",
    ".bat",
    ".ps1",
    ".java",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".sql",
    ".r",
    ".rb",
    ".php",
    ".pl",
    ".go",
    ".rs",
    ".ts",
    ".jsx",
    ".tsx",
    ".vue",
    ".tex",
    ".bib",
    ".toml",
    ".env",
    ".gitignore",
    ".dockerfile",
}

MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024
FIXED_WORKERS: int = 8

# Type aliases
LineFinding = tuple[int, str, str, float]
FileResult = tuple[Path, list[LineFinding] | None, str | None]


def _get_detector() -> gcld3.NNetLanguageIdentifier:
    """Return a lazily-initialized gcld3 language detector for the current process."""
    global _DETECTOR
    if _DETECTOR is None:
        _DETECTOR = gcld3.NNetLanguageIdentifier(min_num_bytes=0, max_num_bytes=1000)
    return _DETECTOR


def is_likely_text_file(path: Path) -> bool:
    """Return True if the file's extension is in the known text-file set."""
    return path.suffix.lower() in TEXT_EXTENSIONS


def detect_language(text: str) -> tuple[str | None, float | None, bool]:
    """Detect the language of a text snippet.

    Returns a tuple of (language_code, probability, is_reliable). For blank
    input, returns (None, None, True).
    """
    if not text.strip():
        return None, None, True
    result = _get_detector().FindLanguage(text=text)
    if result.language == "und":
        return "und", result.probability, result.is_reliable
    return result.language, result.probability, result.is_reliable


def process_file(path: Path) -> FileResult:
    """Scan a single file and return its non-English line findings.

    Returns (path, findings, error). If successful, error is None and findings
    is a (possibly empty) list. On failure, findings is None and error is a
    human-readable message.
    """
    try:
        if path.stat().st_size > MAX_FILE_SIZE_BYTES:
            return path, None, "File too large (>10MB)"
    except (OSError, PermissionError) as exc:
        return path, None, f"Cannot access file: {exc}"

    try:
        content: list[str] | None = None
        for encoding in ("utf-8", "latin-1", "cp1252"):
            try:
                with open(path, "r", encoding=encoding) as handle:
                    content = handle.readlines()
                break
            except UnicodeDecodeError:
                continue

        if content is None:
            return path, None, "Cannot decode file"

        findings: list[LineFinding] = []
        for line_num, line in enumerate(content, 1):
            stripped = line.strip()
            if not stripped:
                continue
            lang, prob, reliable = detect_language(stripped)
            if lang and lang != "en" and reliable and prob is not None:
                findings.append((line_num, stripped, lang, prob))
            elif lang == "und" and not reliable and prob is not None:
                findings.append((line_num, stripped, "und", prob))
        return path, findings, None
    except Exception as exc:  # noqa: BLE001 - reported to caller
        return path, None, f"Error processing file: {exc}"


def find_text_files(
    root_dir: str = ".", extensions: Iterable[str] = TEXT_EXTENSIONS
) -> list[Path]:
    """Recursively find text files under root_dir matching the given extensions."""
    root_path = Path(root_dir)
    text_files: list[Path] = []
    for ext in extensions:
        text_files.extend(root_path.rglob(f"*{ext}"))
    unique_files = list(set(text_files))
    filtered = [f for f in unique_files if is_likely_text_file(f)]
    filtered.sort()
    return filtered


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Find non-English lines in text files using gcld3"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="noneng.txt",
        help="Output report file (default: noneng.txt)",
    )
    parser.add_argument(
        "--extensions",
        nargs="+",
        help="Additional file extensions to scan",
    )
    return parser


def write_report(
    output_path: Path,
    directory: str,
    files_scanned: int,
    files_with_findings: int,
    total_non_eng_lines: int,
    non_english_results: list[tuple[Path, list[LineFinding]]],
    errors: list[tuple[Path, str]],
) -> None:
    """Write the detection report to output_path."""
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write("=" * 40 + "\n")
        handle.write("Non-English Lines Detection Report\n")
        handle.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        handle.write(f"Directory scanned: {Path(directory).resolve()}\n")
        handle.write(f"Files scanned: {files_scanned}\n")
        handle.write(f"Files with non-English content: {files_with_findings}\n")
        handle.write(f"Total non-English lines found: {total_non_eng_lines}\n")
        handle.write("=" * 40 + "\n\n")

        if non_english_results:
            for path, lines in non_english_results:
                handle.write(f"\n{'─' * 40}\n")
                handle.write(f"File: {path}\n")
                handle.write(f"Non-English lines: {len(lines)}\n")
                handle.write(f"{'─' * 40}\n\n")
                for line_num, line_text, lang, prob in lines:
                    handle.write(
                        f"  Line {line_num}: [{lang}] (confidence: {prob:.2f})\n"
                    )
                    handle.write(f"  Content: {line_text}\n\n")
        else:
            handle.write("No non-English lines found.\n")

        if errors:
            handle.write(f"\n{'=' * 40}\n")
            handle.write(f"Errors encountered: {len(errors)}\n")
            handle.write(f"{'=' * 40}\n\n")
            for path, error in errors:
                handle.write(f"  {path}: {error}\n")


def main() -> int:
    """Entry point: parse args, scan files in parallel, and write the report."""
    parser = build_arg_parser()
    args = parser.parse_args()

    extensions: set[str] = set(TEXT_EXTENSIONS)
    if args.extensions:
        extensions.update(args.extensions)

    print(f"Scanning directory: {args.directory}")
    text_files = find_text_files(args.directory, extensions)
    print(f"Found {len(text_files)} text files to process")

    non_english_results: list[tuple[Path, list[LineFinding]]] = []
    errors: list[tuple[Path, str]] = []
    files_with_findings = 0
    total_non_eng_lines = 0

    print(f"Processing files using {FIXED_WORKERS} workers...")
    pool = Pool(processes=FIXED_WORKERS)
    try:
        async_results = [pool.apply_async(process_file, (f,)) for f in text_files]
        completed = 0
        total = len(text_files)
        for async_result in async_results:
            completed += 1
            if completed % 100 == 0 or completed == total:
                print(f"Progress: {completed}/{total} files processed")
            path, results, error = async_result.get()
            if error:
                errors.append((path, error))
            elif results:
                files_with_findings += 1
                total_non_eng_lines += len(results)
                non_english_results.append((path, results))
    finally:
        pool.close()
        pool.join()

    output_path = Path(args.output)
    print(f"Generating report: {output_path}")
    write_report(
        output_path=output_path,
        directory=args.directory,
        files_scanned=len(text_files),
        files_with_findings=files_with_findings,
        total_non_eng_lines=total_non_eng_lines,
        non_english_results=non_english_results,
        errors=errors,
    )

    print("=" * 40)
    print("Scan complete!")
    print(f"Files scanned: {len(text_files)}")
    print(f"Files with non-English content: {files_with_findings}")
    print(f"Total non-English lines found: {total_non_eng_lines}")
    print(f"Errors: {len(errors)}")
    print(f"Report saved to: {output_path.resolve()}")
    print("=" * 40)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
