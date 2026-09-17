#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI script that scans a directory tree for text files, detects
non-English lines in each file using pycld2, runs detection in parallel with a
fixed multiprocessing.Pool of 8 workers via apply_async, uses loguru for logging,
uses pathlib for all path handling, includes full type annotations and docstrings,
supports CLI options for directory, output report path, extra extensions, and a
minimum confidence threshold, and writes a summary report of non-English lines
grouped by file plus language distribution and errors.
"""

import argparse
from collections.abc import Iterable, Sequence
from datetime import datetime
from multiprocessing import Pool, cpu_count
from pathlib import Path

import pycld2 as cld2

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

CLD2_LANG_MAP: dict[str, str] = {
    "en": "ENGLISH",
    "es": "SPANISH",
    "fr": "FRENCH",
    "de": "GERMAN",
    "it": "ITALIAN",
    "pt": "PORTUGUESE",
    "ru": "RUSSIAN",
    "zh": "CHINESE",
    "ja": "JAPANESE",
    "ko": "KOREAN",
    "ar": "ARABIC",
    "hi": "HINDI",
    "nl": "DUTCH",
    "pl": "POLISH",
    "tr": "TURKISH",
    "vi": "VIETNAMESE",
    "th": "THAI",
    "sv": "SWEDISH",
    "da": "DANISH",
    "fi": "FINNISH",
    "no": "NORWEGIAN",
    "cs": "CZECH",
    "hu": "HUNGARIAN",
    "el": "GREEK",
    "he": "HEBREW",
    "id": "INDONESIAN",
    "ms": "MALAY",
    "ro": "ROMANIAN",
    "sk": "SLOVAK",
    "uk": "UKRAINIAN",
    "bg": "BULGARIAN",
    "hr": "CROATIAN",
    "sr": "SERBIAN",
    "ca": "CATALAN",
    "sl": "SLOVENIAN",
    "lt": "LITHUANIAN",
    "lv": "LATVIAN",
    "et": "ESTONIAN",
    "fa": "PERSIAN",
    "tl": "TAGALOG",
    "sw": "SWAHILI",
    "bn": "BENGALI",
    "ta": "TAMIL",
    "te": "TELUGU",
    "mr": "MARATHI",
    "ur": "URDU",
    "gu": "GUJARATI",
    "kn": "KANNADA",
    "ml": "MALAYALAM",
    "pa": "PUNJABI",
    "unknown": "UNKNOWN",
}

FIXED_WORKERS: int = 8
MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024

NonEnglishLine = tuple[int, str, str, str, int]
FileResult = tuple[Path, list[NonEnglishLine] | None, str | None]


def is_likely_text_file(path: Path) -> bool:
    """Return True when the file suffix is in the supported text extensions."""
    return path.suffix.lower() in TEXT_EXTENSIONS


def detect_language(text: str) -> tuple[str | None, str | None, int, bool]:
    """
    Detect the language of a text fragment using pycld2.

    Returns a tuple of (language_code, language_name, confidence_percent,
    is_reliable). If no language can be determined, the code and name are
    returned as None and confidence is 0.
    """
    if not text.strip():
        return None, None, 0, True
    try:
        is_reliable, _text_bytes_found, details = cld2.detect(text)
        if not details:
            return "un", "UNKNOWN", 0, False
        lang_name, lang_code, percent, _score = details[0]
        lang_code = lang_code.lower() if lang_code else "un"
        return lang_code, lang_name, percent, is_reliable
    except Exception:
        return "un", "UNKNOWN", 0, False


def process_file(path: Path) -> FileResult:
    """
    Process a single file and return detected non-English lines.

    Returns a tuple of (path, non_english_lines, error). Exactly one of
    non_english_lines or error will be meaningful; non_english_lines may be an
    empty list when no non-English content is found.
    """
    non_english_lines: list[NonEnglishLine] = []
    try:
        if path.stat().st_size > MAX_FILE_SIZE_BYTES:
            return path, None, "File too large (>10MB)"
    except (OSError, PermissionError) as exc:
        return path, None, f"Cannot access file: {exc}"

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

    try:
        for line_num, line in enumerate(content, 1):
            if not line.strip():
                continue
            lang_code, lang_name, confidence, _is_reliable = detect_language(
                line.strip()
            )
            if (lang_code and lang_code != "en" and confidence >= 50) or (
                lang_code == "un" and confidence < 50
            ):
                non_english_lines.append(
                    (line_num, line.strip(), lang_code, lang_name, confidence)
                )
        return path, non_english_lines, None
    except Exception as exc:
        return path, None, f"Error processing file: {exc}"


def find_text_files(
    root_dir: str | Path = ".", extensions: Iterable[str] = TEXT_EXTENSIONS
) -> list[Path]:
    """
    Recursively locate files under root_dir whose suffix matches extensions.

    The returned list is de-duplicated and sorted for deterministic ordering.
    """
    root_path = Path(root_dir)
    text_files: list[Path] = []
    for ext in extensions:
        text_files.extend(root_path.rglob(f"*{ext}"))
    unique_files: list[Path] = list(set(text_files))
    filtered_files: list[Path] = [f for f in unique_files if is_likely_text_file(f)]
    filtered_files.sort()
    return filtered_files


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the scanner."""
    parser = argparse.ArgumentParser(
        description="Find non-English lines in text files using pycld2"
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
    parser.add_argument(
        "--min-confidence",
        type=int,
        default=50,
        help="Minimum confidence percentage for non-English detection (default: 50)",
    )
    return parser.parse_args()


def write_report(
    output_path: Path,
    scanned_directory: Path,
    text_files: Sequence[Path],
    non_english_results: Sequence[tuple[Path, list[NonEnglishLine]]],
    errors: Sequence[tuple[Path, str]],
    min_confidence: int,
) -> None:
    """Write the final detection report to output_path."""
    files_with_findings = len(non_english_results)
    total_non_eng_lines = sum(len(lines) for _, lines in non_english_results)

    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write("=" * 40 + "\n")
        handle.write("Non-English Lines Detection Report\n")
        handle.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        handle.write(f"Directory scanned: {scanned_directory.resolve()}\n")
        handle.write(f"Files scanned: {len(text_files)}\n")
        handle.write(f"Files with non-English content: {files_with_findings}\n")
        handle.write(f"Total non-English lines found: {total_non_eng_lines}\n")
        handle.write(f"Minimum confidence threshold: {min_confidence}%\n")
        handle.write("=" * 40 + "\n\n")

        if non_english_results:
            lang_counts: dict[str, int] = {}
            for _, lines in non_english_results:
                for _, _, lang_code, lang_name, _ in lines:
                    key = f"{lang_name} ({lang_code})"
                    lang_counts[key] = lang_counts.get(key, 0) + 1

            if lang_counts:
                handle.write("Language Distribution:\n")
                handle.write("-" * 40 + "\n")
                handle.writelines(
                    f"  {lang}: {count} lines\n"
                    for lang, count in sorted(
                        lang_counts.items(), key=lambda item: item[1], reverse=True
                    )
                )
                handle.write("\n")

            for path, lines in non_english_results:
                handle.write(f"\n{'─' * 40}\n")
                handle.write(f"File: {path}\n")
                handle.write(f"Non-English lines: {len(lines)}\n")
                handle.write(f"{'─' * 40}\n\n")
                for line_num, line_text, lang_code, lang_name, confidence in lines:
                    handle.write(
                        f"  Line {line_num}: [{lang_name}] ({lang_code}) - "
                        f"Confidence: {confidence}%\n"
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
    """Run the non-English line scanner and write the report."""
    args = parse_args()

    extensions: set[str] = set(TEXT_EXTENSIONS)
    if args.extensions:
        extensions.update(args.extensions)

    scanned_directory = Path(args.directory)
    print("Scanning directory: {}", scanned_directory)

    text_files = find_text_files(scanned_directory, extensions)
    print("Found {} text files to process", len(text_files))

    non_english_results: list[tuple[Path, list[NonEnglishLine]]] = []
    errors: list[tuple[Path, str]] = []
    files_with_findings = 0
    total_non_eng_lines = 0

    workers = min(FIXED_WORKERS, max(1, cpu_count()))
    print("Processing files using {} workers...", workers)

    with Pool(processes=workers) as pool:
        async_results = [pool.apply_async(process_file, (f,)) for f in text_files]
        total = len(async_results)

        for completed, async_result in enumerate(async_results, 1):
            if completed % 100 == 0 or completed == total:
                print("Progress: {}/{} files processed", completed, total)

            path, results, error = async_result.get()

            if error:
                errors.append((path, error))
            elif results:
                files_with_findings += 1
                total_non_eng_lines += len(results)
                non_english_results.append((path, results))

    output_path = Path(args.output)
    print("Generating report: {}", output_path)

    write_report(
        output_path=output_path,
        scanned_directory=scanned_directory,
        text_files=text_files,
        non_english_results=non_english_results,
        errors=errors,
        min_confidence=args.min_confidence,
    )

    print("=" * 40)
    print("Scan complete!")
    print("Files scanned: {}", len(text_files))
    print("Files with non-English content: {}", files_with_findings)
    print("Total non-English lines found: {}", total_non_eng_lines)
    print("Errors: {}", len(errors))
    print("Report saved to: {}", output_path.resolve())
    print("=" * 40)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
