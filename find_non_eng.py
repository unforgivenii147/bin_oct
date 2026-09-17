#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

import pycld2
from dh import is_binary


class LanguageDetector:
    def __init__(self, min_bytes: int = 100, max_bytes: int = 10000) -> None:
        self.min_bytes = min_bytes
        self.max_bytes = max_bytes
        self.stats = {
            "total_files": 0,
            "skipped_binary": 0,
            "skipped_small": 0,
            "skipped_error": 0,
            "non_english": [],
            "languages": Counter(),
        }

    def is_text_file(self, path: Path) -> bool:
        return not is_binary(path)

    def detect_language(self, path: Path):
        try:
            with Path(path).open(encoding="utf-8", errors="ignore") as f:
                content = f.read(self.max_bytes)
            if len(content) < self.min_bytes:
                return False, "TOO_SHORT", None, None
            is_reliable, _, details = pycld2.detect(content)
            if details and len(details) > 0:
                lang_name, lang_code, percent, _ = details[0]
                return is_reliable, lang_name, lang_code, percent
            return False, "UNKNOWN", None, None
        except pycld2.error as e:
            return False, f"CLD2_ERROR: {e}", None, None
        except Exception as e:
            return False, f"ERROR: {e}", None, None

    def scan_directory(
        self, directory, show_progress=True, only_report_non_english=True
    ) -> None:
        directory = Path(directory)
        if not directory.exists():
            print(f"Error: Directory '{directory}' does not exist")
            return
        print(f"🔍 Scanning directory: {directory.absolute()}")
        print("-" * 40)
        for root, dirs, files in os.walk(directory):
            root_path = Path(root)
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for file in files:
                path = root_path / file
                if file.startswith("."):
                    continue
                self.stats["total_files"] += 1
                if show_progress:
                    print(
                        f"\n{path} [Files: {self.stats['total_files']}]",
                        end="",
                        flush=True,
                    )
                if not self.is_text_file(path):
                    self.stats["skipped_binary"] += 1
                    continue
                is_reliable, lang_name, lang_code, percent = self.detect_language(path)
                if lang_name in {"TOO_SHORT", "UNKNOWN", None} or lang_name.startswith(
                    ("ERROR:", "CLD2_ERROR:")
                ):
                    self.stats[
                        "skipped_small" if lang_name == "TOO_SHORT" else "skipped_error"
                    ] += 1
                    continue
                self.stats["languages"][lang_name] += 1
                if (lang_code != "en" or not only_report_non_english) and (
                    (lang_code == "en" and not is_reliable and only_report_non_english)
                    or lang_code != "en"
                ):
                    self.stats["non_english"].append(
                        {
                            "file": path,
                            "language": lang_name,
                            "code": lang_code,
                            "reliable": is_reliable,
                            "confidence": percent,
                        }
                    )
        print("\n" + "=" * 40)
        self.report_results(only_report_non_english)

    def report_results(self, only_report_non_english=True) -> None:
        print("\n📊 SCAN RESULTS")
        print("-" * 40)
        print(f"📁 Total files processed: {self.stats['total_files']}")
        print(f"⏭️  Skipped binary files: {self.stats['skipped_binary']}")
        print(f"📏 Skipped small files (<100 bytes): {self.stats['skipped_small']}")
        print(f"❌ Skipped (errors): {self.stats['skipped_error']}")
        if only_report_non_english:
            print(f"🌍 Non-English files found: {len(self.stats['non_english'])}")
        else:
            print(
                f"🌍 Total text files analyzed: {sum(self.stats['languages'].values())}"
            )
        if self.stats["languages"]:
            print("\n📈 Language Distribution:")
            for lang, count in self.stats["languages"].most_common():
                print(f"  • {lang}: {count} files")
        if self.stats["non_english"]:
            print(f"\n📝 Non-English Files ({len(self.stats['non_english'])}):")
            print("-" * 40)
            non_english_by_lang = {}
            for item in self.stats["non_english"]:
                lang = item["language"]
                if lang not in non_english_by_lang:
                    non_english_by_lang[lang] = []
                non_english_by_lang[lang].append(item)
            for lang, files in sorted(non_english_by_lang.items()):
                print(f"\n  [{lang}] - {len(files)} files:")
                for item in files[:10]:
                    reliability = "✓" if item["reliable"] else "?"
                    confidence = item["confidence"] or 0
                    rel_str = f"[{reliability} {confidence}%]" if confidence else "[?]"
                    print(f"    {rel_str} {item['file']}")
                if len(files) > 10:
                    print(f"    ... and {len(files) - 10} more")
        else:
            print("\n✅ No non-English files found!")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recursively find non-English files using pycld2"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument(
        "--min-bytes",
        type=int,
        default=100,
        help="Minimum bytes to read for language detection (default: 100)",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=10000,
        help="Maximum bytes to read from each file (default: 10000)",
    )
    parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Report all files, including English ones",
    )
    parser.add_argument(
        "--no-progress", "-np", action="store_true", help="Don't show progress"
    )
    parser.add_argument("--output", "-o", type=str, help="Output results to file")
    args = parser.parse_args()
    detector = LanguageDetector(min_bytes=args.min_bytes, max_bytes=args.max_bytes)
    detector.scan_directory(
        args.directory,
        show_progress=not args.no_progress,
        only_report_non_english=not args.all,
    )
    if args.output:
        from contextlib import redirect_stdout

        with Path(args.output).open("w", encoding="utf-8") as f, redirect_stdout(f):
            detector.report_results(only_report_non_english=not args.all)
        print(f"\n✅ Results saved to: {args.output}")


if __name__ == "__main__":
    try:
        import pycld2
    except ImportError:
        print("Error: pycld2 is not installed. Install it with:")
        print("  pip install pycld2")
        print("\nOn Termux, you might need:")
        print("  pkg install clang")
        print("  pip install pycld2")
        sys.exit(1)
    raise SystemExit(main())
