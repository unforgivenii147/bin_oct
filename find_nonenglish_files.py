#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pycld2
from dh import TXT_EXT

MIN_TEXT_LENGTH = 20
SUPPORTED_EXTENSIONS = TXT_EXT
ENGLISH_LANGUAGES = {"en", "en_US", "en_GB"}
MAX_FILE_SIZE = 1024 * 1024


def detect_language(text: str) -> tuple[str | None, float]:
    if not text or len(text) < MIN_TEXT_LENGTH:
        return None, 0
    try:
        reliable, _, details = pycld2.detect(text)
        if reliable and details:
            primary_lang = details[0][0]
            confidence = details[0][2]
            return primary_lang, confidence
    except Exception:
        pass
    return None, 0


def is_likely_english(text: str, threshold: float = 70.0) -> bool:
    lang, confidence = detect_language(text)
    if lang is None:
        return False
    return lang in ENGLISH_LANGUAGES and confidence >= threshold


def read_file_safely(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        for encoding in ["latin-1", "cp1252", "iso-8859-1"]:
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
    except Exception:
        pass
    return None


def get_file_sample(text: str, max_lines: int = 50, max_chars: int = 5000) -> str:
    lines = text.split("\n")[:max_lines]
    sample = "\n".join(lines)
    if len(sample) > max_chars:
        sample = sample[:max_chars]
    return sample


def analyze_directory(directory: str = ".", show_all: bool = False) -> dict:
    directory = Path(directory).resolve()
    print(f"🔍 Scanning directory: {directory}")
    print("-" * 40)
    results = {
        "total_files": 0,
        "checked_files": 0,
        "skipped_small": 0,
        "skipped_binary": 0,
        "skipped_encoding": 0,
        "non_english": defaultdict(list),
        "english": [],
        "undetermined": [],
        "language_stats": Counter(),
        "directory_stats": defaultdict(lambda: {"total": 0, "non_english": 0}),
    }
    for root, dirs, files in os.walk(directory):
        dirs[:] = [
            d
            for d in dirs
            if not d.startswith(".") and d not in {"__pycache__", "node_modules"}
        ]
        cwd = Path(root)
        rel_dir = cwd.relative_to(directory)
        for file in files:
            path = cwd / file
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if path.stat().st_size > MAX_FILE_SIZE:
                results["skipped_binary"] += 1
                continue
            results["total_files"] += 1
            results["directory_stats"][str(rel_dir)]["total"] += 1
            content = read_file_safely(path)
            if content is None:
                results["skipped_encoding"] += 1
                continue
            sample = get_file_sample(content)
            if len(sample) < MIN_TEXT_LENGTH:
                results["skipped_small"] += 1
                continue
            lang, confidence = detect_language(sample)
            if lang is None:
                results["undetermined"].append(path)
                continue
            results["checked_files"] += 1
            results["language_stats"][lang] += 1
            if lang in ENGLISH_LANGUAGES and confidence >= 70:
                results["english"].append(path)
            else:
                results["non_english"][lang].append(path)
                results["directory_stats"][str(rel_dir)]["non_english"] += 1
    return results


def print_results(results: dict, show_files: bool = False) -> None:
    print("\n" + "=" * 40)
    print("📊 LANGUAGE DETECTION RESULTS")
    print("-" * 40)
    total = results["total_files"]
    checked = results["checked_files"]
    non_english_total = sum(len(files) for files in results["non_english"].values())
    english_total = len(results["english"])
    undetermined = len(results["undetermined"])
    print(f"\n📁 Files scanned: {total}")
    print(f"   ├─ Successfully analyzed: {checked} ({checked / total * 40:.1f}%)")
    print(f"   ├─ Skipped (too small): {results['skipped_small']}")
    print(f"   ├─ Skipped (binary/large): {results['skipped_binary']}")
    print(f"   └─ Skipped (encoding issues): {results['skipped_encoding']}")
    print("\n🌍 Language breakdown:")
    print(f"   ├─ 🇺🇸 English files: {english_total}")
    for lang, files in sorted(
        results["non_english"].items(), key=lambda x: len(x[1]), reverse=True
    ):
        percentage = len(files) / checked * 40 if checked > 0 else 0
        print(f"   ├─ 🌐 {lang.upper()}: {len(files)} files ({percentage:.1f}%)")
    if undetermined > 0:
        print(f"   └─ ❓ Undetermined: {undetermined}")
    if results["directory_stats"]:
        print("\n📂 Directories with most non-English files:")
        dirs_with_non_english = [
            (dir_path, stats)
            for dir_path, stats in results["directory_stats"].items()
            if stats["non_english"] > 0
        ]
        dirs_with_non_english.sort(key=lambda x: x[1]["non_english"], reverse=True)
        for dir_path, stats in dirs_with_non_english[:10]:
            percentage = stats["non_english"] / stats["total"] * 40
            print(f"   ├─ {dir_path if dir_path != '.' else '(root)'}:")
            print(
                f"   │   {stats['non_english']}/{stats['total']} files ({percentage:.1f}% non-English)"
            )
    if show_files and results["non_english"]:
        print("\n📄 Non-English files by language:")
        for lang, files in sorted(results["non_english"].items()):
            if files:
                print(f"\n   🌐 {lang.upper()} ({len(files)} files):")
                for path in files[:20]:
                    rel_path = (
                        path.relative_to(Path.cwd()) if path.is_absolute() else path
                    )
                    print(f"      └─ {rel_path}")
                if len(files) > 20:
                    print(f"      └─ ... and {len(files) - 20} more")
    print("\n" + "=" * 40)
    print("🎯 RECOMMENDATION")
    print("-" * 40)
    if non_english_total == 0:
        print("✅ All files appear to be in English! No translation needed.")
    else:
        print(
            f"📢 Found {non_english_total} non-English files that may need translation."
        )
        dirs_to_translate = [
            (dir_path, stats)
            for dir_path, stats in results["directory_stats"].items()
            if stats["non_english"] > 0
        ]
        if dirs_to_translate:
            print("\n📌 Directories to translate (by priority):")
            for dir_path, stats in sorted(
                dirs_to_translate, key=lambda x: x[1]["non_english"], reverse=True
            ):
                print(f"   └─ {dir_path if dir_path != '.' else 'current directory'}:")
                print(f"       {stats['non_english']} non-English files to translate")
    print("-" * 40)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Find non-English files in directory recursively using pycld2"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show detailed file listing"
    )
    parser.add_argument(
        "-l",
        "--list-languages",
        action="store_true",
        help="List all detected languages and their counts",
    )
    args = parser.parse_args()
    try:
        results = analyze_directory(args.directory)
        print_results(results, show_files=args.verbose or args.list_languages)
    except KeyboardInterrupt:
        print("\n\n⚠️  Scan interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
