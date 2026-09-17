#!/data/data/com.termux/files/home/.local/bin/python
"""
Refactor a Python codebase to convert regex pattern strings into raw strings.

This module walks one or more paths, finds Python files, locates string literals passed
directly to common `re` module functions, and converts those literals into raw strings
when they contain regex escape sequences. It uses tokenization to preserve formatting,
validates modified files with `ast.parse`, optionally creates backups, and supports a
dry-run mode. Concurrency is implemented with `multiprocessing.Pool.apply_async` using a
fixed pool of 8 workers. Logging is handled with `loguru`, and all filesystem paths are
managed via `pathlib`.
"""

from __future__ import annotations

import argparse
import ast
import io
import shutil
import sys
import time
import tokenize
from dataclasses import dataclass, field
from multiprocessing import Pool
from pathlib import Path
from typing import Final

from loguru import logger

RE_FUNCTIONS: Final[set[str]] = {
    "compile",
    "search",
    "match",
    "fullmatch",
    "split",
    "findall",
    "finditer",
    "sub",
    "subn",
}

SKIP_TOKEN_TYPES: Final[set[int]] = {
    tokenize.NL,
    tokenize.COMMENT,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENCODING,
    tokenize.TYPE_COMMENT,
    tokenize.ERRORTOKEN,
}

REGEX_INDICATORS: Final[set[str]] = {
    "\\d",
    "\\w",
    "\\s",
    "\\S",
    "\\W",
    "\\D",
    "\\b",
    "\\B",
    "\\A",
    "\\Z",
    "\\z",
    "[",
    "]",
    "(",
    ")",
    "{",
    "}",
    "|",
    "^",
    "$",
    "+",
    "*",
    "?",
    ".",
    "\\1",
    "\\2",
    "\\3",
    "\\4",
    "\\5",
    "\\6",
    "\\7",
    "\\8",
    "\\9",
    "\\0",
}

FIXED_WORKERS: Final[int] = 8


@dataclass
class StringModification:
    """Represents a single string literal that should be rewritten."""

    start: tuple[int, int]
    end: tuple[int, int]
    original: str
    modified: str
    line_offset: int = 0


@dataclass
class ProcessingStats:
    """Aggregated statistics for a processing run."""

    total_files: int = 0
    processed: int = 0
    modified: int = 0
    errors: int = 0
    skipped: int = 0
    start_time: float = field(default_factory=time.time)

    @property
    def elapsed(self) -> float:
        """Return the number of seconds elapsed since the run started."""
        return time.time() - self.start_time


class RegexFixer:
    """Convert regex string literals to raw strings across Python files."""

    def __init__(
        self,
        create_backup: bool = True,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> None:
        """Initialize the fixer.

        Args:
            create_backup: Whether to create ``.bak`` files before writing.
            dry_run: If ``True``, do not modify files on disk.
            verbose: If ``True``, emit detailed per-file information.
        """
        self.create_backup: bool = create_backup
        self.dry_run: bool = dry_run
        self.verbose: bool = verbose
        self.max_workers: int = FIXED_WORKERS
        self.stats: ProcessingStats = ProcessingStats()

    def should_convert_string(self, content: str) -> bool:
        """Return ``True`` if ``content`` looks like it contains regex syntax."""
        if not content:
            return False
        escape_count: int = 0
        i: int = 0
        while i < len(content) - 1:
            if content[i] == "\\":
                if content[i + 1] in "\\abfnrtv\"'01234567xNuU":
                    escape_count += 1
                    if escape_count >= 2:
                        return True
                    for indicator in REGEX_INDICATORS:
                        if content[i : i + len(indicator)] == indicator:
                            return True
                i += 1
            i += 1
        return bool(any(indicator in content for indicator in REGEX_INDICATORS))

    def parse_string_literal(self, token_str: str) -> tuple[str, str, str, bool]:
        """Split a Python string token into ``(prefix, quote, content, is_raw)``."""
        prefix_end: int = 0
        for ch in token_str:
            if ch in ('"', "'"):
                break
            prefix_end += 1
        else:
            return (token_str, "", "", False)

        prefix: str = token_str[:prefix_end]
        is_raw: bool = "r" in prefix.lower()
        quote_char: str = token_str[prefix_end]
        quote_len: int = 1
        if (
            len(token_str) >= prefix_end + 3
            and token_str[prefix_end : prefix_end + 3] == quote_char * 3
        ):
            quote_len = 3
        opening: str = quote_char * quote_len
        content_start: int = prefix_end + quote_len
        content_end: int = len(token_str) - quote_len
        if content_end <= content_start:
            return (prefix, opening, "", is_raw)
        content: str = token_str[content_start:content_end]
        return (prefix, opening, content, is_raw)

    def convert_string(self, token_str: str) -> str | None:
        """Return the rewritten token, or ``None`` if no rewrite is needed."""
        prefix, opening, content, is_raw = self.parse_string_literal(token_str)
        if is_raw:
            return None
        if "b" in prefix.lower():
            return None
        if not self.should_convert_string(content):
            return None
        new_content: str = content.replace("\\\\", "\\")
        new_prefix: str = prefix
        if "f" in prefix.lower() and "r" not in prefix.lower():
            new_prefix = "rf" + prefix.replace("f", "").replace("F", "")
        elif "r" not in prefix.lower():
            new_prefix = "r" + prefix
        return f"{new_prefix}{opening}{new_content}{opening}"

    def process_tokens(self, code: str) -> list[StringModification]:
        """Find all regex string literals in ``code`` that should be rewritten."""
        modifications: list[StringModification] = []
        try:
            tokens: list[tokenize.TokenInfo] = list(
                tokenize.generate_tokens(io.StringIO(code).readline)
            )
        except tokenize.TokenError:
            return modifications

        relevant: list[tokenize.TokenInfo] = []
        for tok in tokens:
            if tok.type in SKIP_TOKEN_TYPES:
                continue
            if (
                tok.type in (tokenize.NAME, tokenize.OP, tokenize.STRING)
                or tok.type == tokenize.NUMBER
            ):
                relevant.append(tok)

        i: int = 0
        while i < len(relevant) - 4:
            if (
                relevant[i].type == tokenize.NAME
                and relevant[i].string == "re"
                and (i + 1 < len(relevant))
                and (relevant[i + 1].type == tokenize.OP)
                and (relevant[i + 1].string == ".")
                and (i + 2 < len(relevant))
                and (relevant[i + 2].type == tokenize.NAME)
                and (relevant[i + 2].string in RE_FUNCTIONS)
                and (i + 3 < len(relevant))
                and (relevant[i + 3].type == tokenize.OP)
                and (relevant[i + 3].string == "(")
                and (i + 4 < len(relevant))
                and (relevant[i + 4].type == tokenize.STRING)
            ):
                str_token: tokenize.TokenInfo = relevant[i + 4]
                new_str: str | None = self.convert_string(str_token.string)
                if new_str is not None and new_str != str_token.string:
                    modifications.append(
                        StringModification(
                            start=str_token.start,
                            end=str_token.end,
                            original=str_token.string,
                            modified=new_str,
                        )
                    )
                i += 5
            else:
                i += 1
        return modifications

    def apply_modifications(
        self, code: str, modifications: list[StringModification]
    ) -> str:
        """Apply ``modifications`` to ``code`` and return the new source."""
        if not modifications:
            return code
        lines: list[str] = code.splitlines(keepends=True)
        line_offsets: list[int] = [0]
        for line in lines:
            line_offsets.append(line_offsets[-1] + len(line))

        sorted_mods: list[StringModification] = sorted(
            modifications, key=lambda x: (x.start[0], x.start[1]), reverse=True
        )
        result_parts: list[str] = []
        last_end: int = len(code)
        for mod in sorted_mods:
            start_abs: int = line_offsets[mod.start[0] - 1] + mod.start[1]
            end_abs: int = line_offsets[mod.end[0] - 1] + mod.end[1]
            result_parts.append(code[end_abs:last_end])
            result_parts.append(mod.modified)
            last_end = start_abs
        result_parts.append(code[:last_end])
        result_parts.reverse()
        return "".join(result_parts)

    def validate_code(self, code: str) -> bool:
        """Return ``True`` if ``code`` parses as valid Python."""
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False

    def process_file(self, path: Path) -> tuple[Path, bool, str]:
        """Process a single file and return ``(path, success, message)``."""
        try:
            original_code: str = path.read_text(encoding="utf-8")
        except Exception as e:
            return (path, False, f"Failed to read: {e}")

        if "re." not in original_code:
            return (path, True, "No re calls found")

        modifications: list[StringModification] = self.process_tokens(original_code)
        if not modifications:
            return (path, True, "No changes needed")

        if self.verbose:
            print(f"Found {len(modifications)} modification(s) in {path.name}")
            for mod in modifications:
                logger.debug(f"  {mod.original} -> {mod.modified}")

        new_code: str = self.apply_modifications(original_code, modifications)
        if not self.validate_code(new_code):
            return (
                path,
                False,
                "Validation failed - syntax error after conversion",
            )

        if self.dry_run:
            return (path, True, f"Would modify {len(modifications)} string(s)")

        if self.create_backup:
            backup_path: Path = path.with_suffix(path.suffix + ".bak")
            try:
                shutil.copy2(path, backup_path)
            except Exception as e:
                return (path, False, f"Failed to create backup: {e}")

        try:
            path.write_text(new_code, encoding="utf-8")
            return (path, True, f"✓ Modified {len(modifications)} string(s)")
        except Exception as e:
            return (path, False, f"Failed to write: {e}")

    def collect_files(self, paths: list[Path]) -> list[Path]:
        """Collect all Python files under ``paths``, excluding common junk dirs."""
        python_files: set[Path] = set()
        exclude_dirs: Final[set[str]] = {
            ".venv",
            "venv",
            "env",
            "__pycache__",
            ".git",
            ".hg",
            ".svn",
            "node_modules",
            "dist",
            "build",
            ".tox",
            ".pytest_cache",
        }
        for path in paths:
            if not path.exists():
                logger.warning(f"Path does not exist: {path}")
                continue
            if path.is_file():
                if path.suffix == ".py":
                    python_files.add(path)
            elif path.is_dir():
                for py_file in path.rglob("*.py"):
                    if any(part in exclude_dirs for part in py_file.parts):
                        continue
                    python_files.add(py_file)
        return sorted(python_files)

    def process_files(self, files: list[Path]) -> list[tuple[Path, bool, str]]:
        """Process ``files`` using a fixed pool of workers."""
        if not files:
            return []
        self.stats.total_files = len(files)

        if len(files) == 1:
            results: list[tuple[Path, bool, str]] = []
            for path in files:
                result = self.process_file(path)
                results.append(result)
                self._update_stats(result)
            return results

        results = []
        with Pool(processes=FIXED_WORKERS) as pool:
            async_results = [pool.apply_async(self.process_file, (f,)) for f in files]
            for i, async_result in enumerate(async_results, 1):
                try:
                    result = async_result.get()
                    results.append(result)
                    self._update_stats(result)
                    if self.verbose and i % 10 == 0:
                        print(f"Progress: {i}/{len(files)}")
                except Exception as e:
                    results.append((files[i - 1], False, f"Error: {e}"))
                    self.stats.errors += 1
        return results

    def _update_stats(self, result: tuple[Path, bool, str]) -> None:
        """Update internal counters from a single file result."""
        _, success, message = result
        if success:
            self.stats.processed += 1
            if "Modified" in message or "Would modify" in message:
                self.stats.modified += 1
            elif "No changes" in message:
                self.stats.skipped += 1
        else:
            self.stats.errors += 1

    def print_summary(self, results: list[tuple[Path, bool, str]]) -> None:
        """Emit a human-readable summary of the run."""
        if not results:
            print("No files processed.")
            return

        print("=" * 40)
        modified: list[tuple[Path, str]] = []
        unchanged: list[tuple[Path, str]] = []
        errors: list[tuple[Path, str]] = []
        for path, success, message in results:
            if not success:
                errors.append((path, message))
            elif "Modified" in message or "Would modify" in message:
                modified.append((path, message))
            else:
                unchanged.append((path, message))

        if modified:
            print("📝 Modified files:")
            for path, message in modified:
                rel_path: str = self._get_relative_path(path)
                print(f"  ✓ {rel_path}")
                if self.verbose:
                    print(f"    {message}")

        if errors:
            logger.error("❌ Errors:")
            for path, message in errors:
                rel_path = self._get_relative_path(path)
                logger.error(f"  ✗ {rel_path}: {message}")

        print("=" * 40)
        print("📊 Summary:")
        print(f"  Total files:     {self.stats.total_files}")
        print(f"  Processed:       {self.stats.processed}")
        print(f"  Modified:        {self.stats.modified}")
        print(f"  Unchanged:       {self.stats.skipped}")
        print(f"  Errors:          {self.stats.errors}")
        print(f"  Time elapsed:    {self.stats.elapsed:.2f}s")
        print(f"  Workers:         {self.max_workers}")
        print(f"  Backup:          {('Enabled' if self.create_backup else 'Disabled')}")
        print(f"  Dry run:         {('Yes' if self.dry_run else 'No')}")

    def _get_relative_path(self, path: Path) -> str:
        """Return ``path`` relative to the current working directory if possible."""
        try:
            return str(path.relative_to(Path.cwd()))
        except ValueError:
            return str(path)


def main() -> int:
    """Parse CLI arguments, run the fixer, and return an exit code."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Fix regex string literals in Python files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "\nExamples:\n"
            "  # Fix all Python files in current directory\n"
            "  python fix_regex.py\n\n"
            "  # Fix specific files or directories\n"
            "  python fix_regex.py src/ tests/test_regex.py\n\n"
            "  # Preview changes without modifying files\n"
            "  python fix_regex.py --dry-run --verbose\n"
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument(
        "--no-backup", default=True, action="store_true", help="Disable backup creation"
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        default=True,
        action="store_true",
        help="Preview changes without modifying files",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        default=True,
        action="store_true",
        help="Show detailed output",
    )
    parser.add_argument("--quiet", "-q", action="store_true", help="Minimize output")
    args: argparse.Namespace = parser.parse_args()

    if args.quiet:
        logger.remove()
        logger.add(sys.stderr, level="ERROR")

    if args.paths:
        paths: list[Path] = [Path(p).resolve() for p in args.paths]
    else:
        paths = [Path.cwd()]

    fixer: RegexFixer = RegexFixer(
        create_backup=not args.no_backup,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    print(f"📁 Collecting Python files from {len(paths)} path(s)...")
    files: list[Path] = fixer.collect_files(paths)
    if not files:
        logger.warning("No Python files found.")
        return 0

    print(f"✅ Found {len(files)} Python files")
    print(f"🔧 Processing with {fixer.max_workers} worker(s)")
    print(f"💾 Backup: {('Enabled' if fixer.create_backup else 'Disabled')}")
    if fixer.dry_run:
        print("🔍 DRY RUN - No files will be modified")

    results: list[tuple[Path, bool, str]] = fixer.process_files(files)
    fixer.print_summary(results)

    return 1 if fixer.stats.errors > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
