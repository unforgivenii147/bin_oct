#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from multiprocessing import Pool, cpu_count
from pathlib import Path

try:
    import pytesseract
    from PIL import Image
except ImportError:
    print("Error: Required packages not installed.")
    print("Install with: pip install pillow pytesseract")
    sys.exit(1)


@dataclass
class ExtractionResult:
    path: Path
    success: bool
    text: str = ""
    error: str = ""
    char_count: int = 0
    line_count: int = 0


class TextExtractor:
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp", ".gif"}

    @staticmethod
    def extract_from_image(image_path: Path) -> ExtractionResult:
        try:
            if not image_path.exists():
                return ExtractionResult(
                    path=image_path, success=False, error="File not found"
                )
            image = Image.open(image_path)
            text = pytesseract.image_to_string(image, lang="rus+eng")
            print(text)
            txt_path = image_path.with_suffix(".txt")
            txt_path.write_text(text, encoding="utf-8")
            if not text.strip():
                return ExtractionResult(
                    path=image_path,
                    success=True,
                    text="",
                    char_count=0,
                    line_count=0,
                )
            char_count = len(text)
            line_count = len(text.strip().split("\n"))
            return ExtractionResult(
                path=image_path,
                success=True,
                text=text,
                char_count=char_count,
                line_count=line_count,
            )
        except Exception as e:
            return ExtractionResult(path=image_path, success=False, error=str(e))

    @staticmethod
    def find_images(directories: list[Path]) -> list[Path]:
        images = []
        for directory in directories:
            if not directory.is_dir():
                print(f"⚠ Warning: {directory} is not a directory, skipping")
                continue
            for ext in TextExtractor.IMAGE_EXTENSIONS:
                images.extend(directory.rglob(f"*{ext}"))
                images.extend(directory.rglob(f"*{ext.upper()}"))
        return sorted(set(images))


class TextExtractionReport:
    @staticmethod
    def print_header(total_files: int) -> None:
        print("\n" + "=" * 40)
        print("📄 TEXT EXTRACTION REPORT")
        print(f"⏱  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📊 Total files to process: {total_files}")
        print("-" * 40)

    @staticmethod
    def print_file_result(result: ExtractionResult, rel_path: Path) -> None:
        if result.success:
            status = "✓ SUCCESS"
            stats = f"│ Characters: {result.char_count:,} | Lines: {result.line_count}"
        else:
            status = "✗ ERROR"
            stats = f"│ Error: {result.error}"
        print(f"{status:12} │ {rel_path}")
        print(f"{stats}")
        print()

    @staticmethod
    def print_summary(results: list[ExtractionResult], base_paths: list[Path]) -> None:
        for r in results:
            print(r)
        successful = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)
        total_chars = sum(r.char_count for r in results if r.success)
        total_lines = sum(r.line_count for r in results if r.success)
        print("-" * 40)
        print("📊 SUMMARY")
        print("-" * 40)
        print(f"✓ Successful: {successful}/{len(results)}")
        print(f"✗ Failed:     {failed}/{len(results)}")
        print(f"📝 Total characters extracted: {total_chars:,}")
        print(f"📄 Total lines extracted:      {total_lines:,}")
        print("-" * 40)

    @staticmethod
    def save_json_report(results: list[ExtractionResult], output_path: Path) -> None:
        data = {
            "timestamp": datetime.now().isoformat(),
            "total_files": len(results),
            "successful": sum(1 for r in results if r.success),
            "failed": sum(1 for r in results if not r.success),
            "results": [
                {
                    "file": str(r.path),
                    "success": r.success,
                    "char_count": r.char_count,
                    "line_count": r.line_count,
                    "error": r.error if not r.success else None,
                    "preview": r.text[:200] if r.text else "",
                }
                for r in results
            ],
        }
        output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"📋 Detailed report saved to: {output_path}")


def process_image_worker(image_path: Path) -> ExtractionResult:
    return TextExtractor.extract_from_image(image_path)


def main():
    parser = argparse.ArgumentParser(
        description="Extract Russian and English text from images using OCR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s /path/to/dir1 /path/to/dir2
  %(prog)s . --workers 4
  %(prog)s . --json report.json
        """,
    )
    parser.add_argument(
        "directories",
        nargs="*",
        type=Path,
        default=[Path.cwd()],
        help="Directories to process (default: current directory)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=cpu_count(),
        help=f"Number of parallel workers (default: {cpu_count()})",
    )
    parser.add_argument(
        "-j", "--json", type=Path, help="Save detailed report to JSON file"
    )
    parser.add_argument(
        "-s",
        "--silent",
        action="store_true",
        help="Suppress file-by-file output (summary only)",
    )
    args = parser.parse_args()
    directories = [d.resolve() for d in args.directories]
    print("🔍 Scanning for images...")
    images = TextExtractor.find_images(directories)
    if not images:
        print("❌ No images found in the specified directories.")
        return 1
    print(f"✓ Found {len(images)} image(s)\n")
    print(f"⚙️  Processing with {args.workers} worker(s)...\n")
    if not args.silent:
        TextExtractionReport.print_header(len(images))
    with Pool(processes=args.workers) as pool:
        results = pool.map(process_image_worker, images)
    if not args.silent:
        for result, img_path in zip(results, images, strict=False):
            try:
                rel_path = img_path.relative_to(Path.cwd())
            except ValueError:
                rel_path = img_path
            TextExtractionReport.print_file_result(result, rel_path)
    TextExtractionReport.print_summary(results, directories)
    if args.json:
        TextExtractionReport.save_json_report(results, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
