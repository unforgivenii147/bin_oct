#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that recursively scans a directory for text files,
detects non-English content using lingua-language-detector, and outputs
a JSON report. Use multiprocessing.Pool.apply_async with a fixed pool of
8 workers. Use loguru for logging, pathlib for paths, and full type hints.
"""

import argparse
import json
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from lingua import Language, LanguageDetector, LanguageDetectorBuilder
from loguru import logger

TEXT_EXTENSIONS: set[str] = {
    ".txt",
    ".py",
    ".js",
    ".html",
    ".css",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".md",
    ".rst",
    ".csv",
    ".tsv",
    ".log",
    ".sh",
    ".bash",
    ".c",
    ".cpp",
    ".h",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".scala",
    ".lua",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".properties",
    ".env",
}

SKIP_DIRS: set[str] = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "build",
    "dist",
}

BATCH_SIZE: int = 100
MAX_WORKERS: int = 8

_DETECTOR: LanguageDetector | None = None


def _get_detector() -> LanguageDetector:
    """Return a singleton lingua LanguageDetector instance."""
    global _DETECTOR
    if _DETECTOR is None:
        _DETECTOR = LanguageDetectorBuilder.from_all_languages().build()
    return _DETECTOR


def is_english(text: str) -> tuple[bool, float]:
    """Detect whether a short text snippet is English.

    Args:
        text: The text to analyze.

    Returns:
        A tuple of (is_english, confidence). Confidence is 0.0 when the
        detector is unsure, 1.0 for empty/very short text.
    """
    if not text or len(text.strip()) < 3:
        return (True, 1.0)
    try:
        detector = _get_detector()
        confidence_values = detector.compute_language_confidence_values(text)
        if not confidence_values:
            return (True, 0.0)
        best = confidence_values[0]
        is_en = best.language == Language.ENGLISH
        return (is_en, float(best.value))
    except Exception:
        return (True, 0.0)


def _read_file_content(path: Path) -> str | None:
    """Read a file trying several encodings.

    Args:
        path: Path to the file.

    Returns:
        The file content as a string, or None if reading failed.
    """
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            return path.read_text(encoding=encoding, errors="ignore")
        except UnicodeDecodeError:
            continue
        except OSError:
            return None
    return None


def _collect_non_english_lines(lines: list[str]) -> list[dict[str, Any]]:
    """Return detailed information for each non-English line.

    Args:
        lines: The lines of a file.

    Returns:
        A list of dictionaries with line number, text, confidence, and full text.
    """
    non_eng_lines: list[dict[str, Any]] = []
    for idx, line in enumerate(lines, 1):
        if not line.strip():
            continue
        is_en, prob = is_english(line)
        if not is_en:
            non_eng_lines.append(
                {
                    "line_num": idx,
                    "text": line[:200],
                    "confidence": prob,
                    "full_text": line if len(line) <= 200 else f"{line[:200]}...",
                }
            )
    return non_eng_lines


def analyze_file(
    path: Path,
    detailed: bool = False,
) -> dict[str, Any] | None:
    """Analyze a single file for non-English content.

    Args:
        path: Path to the file to analyze.
        detailed: If True, include per-line non-English details.

    Returns:
        A result dictionary if non-English content is found, otherwise None.
    """
    try:
        content = _read_file_content(path)
        if content is None:
            return None

        lines = content.splitlines()
        if not lines:
            return None

        file_result = _get_detector().detect_language_of(content[:10000])
        if file_result is not None and file_result != Language.ENGLISH:
            confidence_values = _get_detector().compute_language_confidence_values(
                content[:10000]
            )
            confidence = float(confidence_values[0].value) if confidence_values else 0.0
            result: dict[str, Any] = {
                "file": str(path),
                "language": file_result.name.lower(),
                "confidence": confidence,
                "size_bytes": path.stat().st_size,
                "line_count": len(lines),
                "non_english_lines": [],
            }
            if detailed:
                non_eng_lines = _collect_non_english_lines(lines)
                if non_eng_lines:
                    result["non_english_lines"] = non_eng_lines
                    result["non_eng_line_count"] = len(non_eng_lines)
            return result

        if detailed:
            non_eng_lines = _collect_non_english_lines(lines)
            if non_eng_lines:
                return {
                    "file": str(path),
                    "language": "en",
                    "confidence": 1.0,
                    "size_bytes": path.stat().st_size,
                    "line_count": len(lines),
                    "non_english_lines": non_eng_lines,
                    "non_eng_line_count": len(non_eng_lines),
                    "mixed": True,
                }

        return None
    except Exception as e:
        return {"file": str(path), "error": str(e), "non_english_lines": []}


def _analyze_file_wrapper(
    args: tuple[Path, bool],
) -> dict[str, Any] | None:
    """Wrapper for analyze_file to unpack arguments for Pool.apply_async.

    Args:
        args: A tuple of (path, detailed).

    Returns:
        The result of analyze_file.
    """
    return analyze_file(*args)


def scan_files(
    root_dir: Path,
    detailed: bool = False,
) -> list[dict[str, Any]]:
    """Recursively scan a directory for non-English text files.

    Args:
        root_dir: The root directory to scan.
        detailed: If True, include per-line non-English details.

    Returns:
        A list of result dictionaries for files with non-English content.
    """
    files: list[Path] = []
    for ext in TEXT_EXTENSIONS:
        files.extend(root_dir.rglob(f"*{ext}"))
    files = [f for f in files if not any(part in SKIP_DIRS for part in f.parts)]

    print(f"Found {len(files)} text files. Analyzing with {MAX_WORKERS} workers...")

    results: list[dict[str, Any]] = []
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [
            pool.apply_async(_analyze_file_wrapper, ((f, detailed),)) for f in files
        ]
        completed = 0
        for async_result in async_results:
            completed += 1
            if completed % 50 == 0:
                print(f"Progress: {completed}/{len(files)} files...")
            try:
                result = async_result.get()
                if result:
                    results.append(result)
            except Exception as e:
                logger.error(f"Error analyzing file: {e}")

    return results


def main() -> int:
    """Entry point for the non-English file scanner.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    parser = argparse.ArgumentParser(description="Find non-English files recursively")
    parser.add_argument(
        "-l",
        "--detailed",
        action="store_true",
        help="Report non-English lines within each file",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="noneng.json",
        help="Output JSON file (default: noneng.json)",
    )
    parser.add_argument(
        "-d",
        "--dir",
        default=".",
        help="Root directory to scan (default: current directory)",
    )
    args = parser.parse_args()

    root_dir = Path(args.dir).resolve()
    if not root_dir.exists():
        logger.error(f"Directory {root_dir} does not exist")
        return 1

    print(f"Scanning: {root_dir}")
    print(f"Detailed mode: {args.detailed}")

    results = scan_files(root_dir, args.detailed)
    results.sort(key=lambda x: x.get("file", ""))

    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "scan_root": str(root_dir),
                "detailed": args.detailed,
                "total_non_english_files": len(results),
                "results": results,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"{'=' * 40}")
    print(f"Found {len(results)} non-English files")
    print(f"Results saved to: {output_path}")

    if results:
        print("Sample (first 5 files):")
        for r in results[:5]:
            lang = r.get("language", "unknown")
            lines = r.get("non_eng_line_count", 0)
            print(f"  {r['file']} → {lang} (confidence: {r.get('confidence', 0):.2%})")
            if args.detailed and lines:
                print(f"    {lines} non-English lines")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
