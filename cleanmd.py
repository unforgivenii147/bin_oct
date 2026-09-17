#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from enum import Enum
from multiprocessing import Pool
from pathlib import Path
from typing import NamedTuple


class Color(Enum):
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"


class Styling:
    @staticmethod
    def style(text: str, color: Color, bold: bool = False) -> str:
        bold_code = Color.BOLD.value if bold else ""
        return f"{bold_code}{color.value}{text}{Color.RESET.value}"

    @staticmethod
    def success(text: str) -> str:
        return Styling.style(text, Color.BRIGHT_GREEN)

    @staticmethod
    def error(text: str) -> str:
        return Styling.style(text, Color.BRIGHT_RED)

    @staticmethod
    def warning(text: str) -> str:
        return Styling.style(text, Color.BRIGHT_YELLOW)

    @staticmethod
    def info(text: str) -> str:
        return Styling.style(text, Color.BRIGHT_CYAN)

    @staticmethod
    def dim(text: str) -> str:
        return Styling.style(text, Color.DIM)


class ImageStats(NamedTuple):
    path: Path
    rel_path: str
    images_removed: int
    references_removed: int
    original_size: int
    final_size: int
    error: str | None


@dataclass
class ProcessingConfig:
    workers: int = 4
    chunk_size: int = 8192
    encoding: str = "utf-8"
    backup: bool = False


class MarkdownPatterns:
    INLINE_IMAGE = re.compile(r"!\[([^\[\]]*)\]\(([^\)]+)\)", re.MULTILINE)
    HTML_IMG_TAG = re.compile(
        r"<img\s+[^>]*src=['\"]?([^'\">\s]+)['\"]?[^>]*/?>\s*",
        re.IGNORECASE | re.MULTILINE,
    )
    REFERENCE_IMAGE = re.compile(r"!\[([^\[\]]*)\]\[([^\[\]]+)\]", re.MULTILINE)
    IMAGE_DEF = re.compile(
        r"^\s*\[([^\[\]]+)\]:\s*(.+?(?:\.(?:png|jpg|jpeg|gif|webp|svg|bmp))?)\s*(?:\"[^\"]*\")?\s*$",
        re.MULTILINE | re.IGNORECASE,
    )
    PICTURE_TAG = re.compile(r"<picture\s*>.*?</picture>", re.DOTALL | re.IGNORECASE)
    FIGURE_TAG = re.compile(r"<figure\s*>.*?</figure>", re.DOTALL | re.IGNORECASE)


class MarkdownImageRemover:
    def __init__(self, config: ProcessingConfig):
        self.config = config
        self.patterns = MarkdownPatterns()

    def remove_images(self, content: str) -> tuple[str, int]:
        original_len = len(content)
        count = 0
        content, inline_count = self._remove_pattern(
            content, self.patterns.INLINE_IMAGE
        )
        count += inline_count
        content, ref_count = self._remove_pattern(
            content, self.patterns.REFERENCE_IMAGE
        )
        count += ref_count
        content, def_count = self._remove_pattern(content, self.patterns.IMAGE_DEF)
        count += def_count
        content, html_count = self._remove_pattern(content, self.patterns.HTML_IMG_TAG)
        count += html_count
        content, pic_count = self._remove_pattern(content, self.patterns.PICTURE_TAG)
        count += pic_count
        content, fig_count = self._remove_pattern(content, self.patterns.FIGURE_TAG)
        count += fig_count
        content = re.sub(r"\n\n\n+", "\n\n", content)
        return content.rstrip() + "\n", count

    def _remove_pattern(self, content: str, pattern: re.Pattern) -> tuple[str, int]:
        matches = list(pattern.finditer(content))
        if not matches:
            return content, 0
        for match in reversed(matches):
            content = content[: match.start()] + content[match.end() :]
        return content, len(matches)


def get_markdown_files(path: Path) -> list[Path]:
    if path.is_file():
        if path.suffix.lower() in {".md", ".markdown"}:
            return [path]
        return []
    if path.is_dir():
        return list(path.rglob("*.md")) + list(path.rglob("*.markdown"))
    return []


def process_file(path: Path, config: ProcessingConfig) -> ImageStats:
    try:
        original_content = path.read_text(encoding=config.encoding)
        original_size = len(original_content.encode(config.encoding))
        remover = MarkdownImageRemover(config)
        cleaned_content, images_removed = remover.remove_images(original_content)
        references_removed = images_removed
        if cleaned_content != original_content:
            if config.backup:
                backup_path = path.with_suffix(path.suffix + ".bak")
                path.write_text(original_content, encoding=config.encoding)
            path.write_text(cleaned_content, encoding=config.encoding)
        final_size = len(cleaned_content.encode(config.encoding))
        return ImageStats(
            path=path,
            rel_path=str(path.relative_to(Path.cwd())),
            images_removed=images_removed,
            references_removed=references_removed,
            original_size=original_size,
            final_size=final_size,
            error=None,
        )
    except Exception as e:
        return ImageStats(
            path=path,
            rel_path=str(path.relative_to(Path.cwd())),
            images_removed=0,
            references_removed=0,
            original_size=0,
            final_size=0,
            error=str(e),
        )


def worker_process_file(args: tuple[Path, ProcessingConfig]) -> ImageStats:
    path, config = args
    return process_file(path, config)


class Reporter:
    @staticmethod
    def print_header():
        print()
        print(Styling.style("=" * 40, Color.BRIGHT_CYAN, bold=True))
        print(
            Styling.style("  Markdown Image Remover v1.0", Color.BRIGHT_CYAN, bold=True)
        )
        print(Styling.style("=" * 40, Color.BRIGHT_CYAN, bold=True))
        print()

    @staticmethod
    def print_file_result(stats: ImageStats):
        if stats.error:
            print(
                f"{Styling.error('✗')} {stats.rel_path}\n"
                f"  {Styling.error('Error')}: {stats.error}"
            )
            return
        reduction = stats.original_size - stats.final_size
        reduction_pct = (
            (reduction / stats.original_size * 40) if stats.original_size > 0 else 0
        )
        status = Styling.success("✓") if stats.images_removed > 0 else Styling.dim("∘")
        print(
            f"{status} {Styling.info(stats.rel_path)}\n"
            f"  Images removed: {Styling.style(str(stats.images_removed), Color.YELLOW, bold=True)} | "
            f"Size: {Styling.dim(Reporter._format_size(stats.original_size))} → "
            f"{Styling.dim(Reporter._format_size(stats.final_size))} "
            f"{Styling.dim(f'(-{reduction_pct:.1f}%)')}"
        )

    @staticmethod
    def print_summary(results: list[ImageStats]):
        print()
        print(Styling.style("-" * 40, Color.BRIGHT_CYAN))
        successful = [r for r in results if not r.error]
        failed = [r for r in results if r.error]
        total_images = sum(r.images_removed for r in successful)
        total_original = sum(r.original_size for r in successful)
        total_final = sum(r.final_size for r in successful)
        total_reduction = total_original - total_final
        reduction_pct = (
            (total_reduction / total_original * 40) if total_original > 0 else 0
        )
        print(f"\n{Styling.style('SUMMARY', Color.BRIGHT_CYAN, bold=True)}")
        print(
            f"  Files processed: {Styling.style(str(len(successful)), Color.BRIGHT_GREEN, bold=True)}"
        )
        if failed:
            print(f"  Failed: {Styling.error(str(len(failed)))}")
        print(
            f"  Total images removed: {Styling.style(str(total_images), Color.YELLOW, bold=True)}"
        )
        print(
            f"  Total size reduction: {Styling.style(Reporter._format_size(total_reduction), Color.BRIGHT_GREEN)} "
            f"{Styling.dim(f'(-{reduction_pct:.1f}%)')}"
        )
        print()

    @staticmethod
    def _format_size(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"


def main():
    Reporter.print_header()
    args = sys.argv[1:]
    if not args:
        search_path = Path.cwd()
        print(
            f"No input provided. Processing {Styling.info(str(search_path))} recursively...\n"
        )
        files = get_markdown_files(search_path)
    else:
        files = []
        for arg in args:
            p = Path(arg)
            files.extend(get_markdown_files(p))
    if not files:
        print(Styling.warning("No markdown files found."))
        sys.exit(0)
    print(
        f"Found {Styling.style(str(len(files)), Color.BRIGHT_YELLOW, bold=True)} "
        f"markdown file(s) to process.\n"
    )
    config = ProcessingConfig(workers=4)
    results = []
    try:
        with Pool(processes=config.workers) as pool:
            file_args = [(f, config) for f in files]
            async_results = [
                pool.apply_async(worker_process_file, (args,)) for args in file_args
            ]
            for async_result in async_results:
                try:
                    result = async_result.get(timeout=30)
                    results.append(result)
                    Reporter.print_file_result(result)
                except Exception as e:
                    print(Styling.error(f"✗ Worker error: {e}"))
    except KeyboardInterrupt:
        print(Styling.warning("\n\nInterrupted by user."))
        sys.exit(1)
    Reporter.print_summary(results)
    failed_count = sum(1 for r in results if r.error)
    sys.exit(1 if failed_count > 0 else 0)


if __name__ == "__main__":
    raise SystemExit(main())
