#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI tool that scans Python files, extracts their purpose from
module docstrings, argparse epilogs, or main() docstrings, suggests meaningful
snake_case filenames from that purpose, and optionally renames files in place.
Use multiprocessing.Pool.apply_async with a fixed pool of 8 workers for
concurrency, loguru for logging, pathlib for all path handling, full type
annotations, and docstrings on all public functions and classes.
"""

from __future__ import annotations

import argparse
import ast
import re
from collections.abc import Generator
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

from loguru import logger

MAX_WORKERS: int = 8
DEFAULT_WORKERS: int = 8


@dataclass
class FileStats:
    """Statistics and rename outcome for a single Python file."""

    path: Path
    current_name: str
    suggestion: str | None
    has_meaning: bool
    error: str | None = None
    renamed: bool = False
    new_path: Path | None = None


class FileAnalyzer:
    """Analyze a Python file to determine whether its filename is meaningful."""

    path: Path
    tree: ast.Module | None
    content: str

    def __init__(self, path: Path) -> None:
        """Parse *path* and read its contents for later inspection."""
        self.path = path
        self.tree = None
        self.content = ""
        try:
            self.content = path.read_text(encoding="utf-8", errors="ignore")
            self.tree = ast.parse(self.content)
        except SyntaxError:
            pass
        except Exception as e:
            raise RuntimeError(f"Failed to read {path}: {e}") from e

    def get_module_docstring(self) -> str | None:
        """Return the module-level docstring, if any."""
        if not self.tree:
            return None
        return ast.get_docstring(self.tree)

    def get_argparse_epilog(self) -> str | None:
        """Return the value of an argparse ``epilog=`` keyword, if present."""
        pattern = r'epilog\s*=\s*[\'"]([^\'"]+)[\'"]'
        match = re.search(pattern, self.content, re.IGNORECASE)
        return match.group(1) if match else None

    def get_main_docstring(self) -> str | None:
        """Return the docstring of a top-level ``main`` function, if any."""
        if not self.tree:
            return None
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                return ast.get_docstring(node)
        return None

    def extract_purpose(self) -> str | None:
        """Derive a human-readable purpose from docstrings or argparse epilog."""
        return (
            self.get_module_docstring()
            or self.get_argparse_epilog()
            or self.get_main_docstring()
        )

    def is_meaningful_name(self) -> bool:
        """Return True when the filename stem looks descriptive enough."""
        name = self.path.stem
        if len(name) < 3 or name in {"main", "run", "test", "script", "app"}:
            return False
        return not re.match(r"^[a-z0-9]{1,2}$", name)

    def suggest_name(self) -> str | None:
        """Suggest a snake_case filename derived from the file's purpose."""
        purpose = self.extract_purpose()
        if not purpose:
            return None
        words = re.findall(r"\b[a-z][a-z0-9]*\b", purpose.lower())
        if not words:
            return None
        stop_words = {
            "this",
            "that",
            "from",
            "with",
            "for",
            "the",
            "and",
            "or",
            "are",
            "is",
        }
        keywords = [w for w in words if len(w) > 3 and w not in stop_words]
        if keywords:
            return "_".join(keywords[:3])
        return "_".join(words[:2]) if len(words) >= 2 else None


def collect_py_files(paths: list[Path]) -> Generator[Path, None, None]:
    """Yield every ``*.py`` file reachable from the given files and directories."""
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            yield path
        elif path.is_dir():
            yield from path.rglob("*.py")


def analyze_file(path: Path) -> FileStats:
    """Analyze a single file and return its :class:`FileStats` record."""
    stats = FileStats(
        path=path,
        current_name=path.stem,
        suggestion=None,
        has_meaning=False,
    )
    try:
        analyzer = FileAnalyzer(path)
        stats.has_meaning = analyzer.is_meaningful_name()
        if not stats.has_meaning:
            stats.suggestion = analyzer.suggest_name()
    except Exception as e:
        stats.error = str(e)
    return stats


def rename_file(path: Path, new_name: str) -> tuple[bool, str | None]:
    """Rename *path* to ``new_name.py`` in the same directory."""
    try:
        new_path = path.parent / f"{new_name}.py"
        if new_path == path:
            return False, "New name is identical to current"
        if new_path.exists():
            return False, f"Target already exists: {new_path.name}"
        path.rename(new_path)
        return True, None
    except Exception as e:
        return False, str(e)


def process_files(paths: list[Path], apply: bool = False) -> list[FileStats]:
    """Analyze all Python files under *paths* using a pool of 8 workers."""
    results: list[FileStats] = []
    file_list = list(collect_py_files(paths))
    if not file_list:
        return results

    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [
            (pool.apply_async(analyze_file, (path,)), path) for path in file_list
        ]
        for async_result, path in async_results:
            try:
                stats = async_result.get()
            except Exception as e:
                stats = FileStats(
                    path=path,
                    current_name=path.stem,
                    suggestion=None,
                    has_meaning=False,
                    error=str(e),
                )
            if not stats.has_meaning and stats.suggestion and apply:
                renamed, error = rename_file(stats.path, stats.suggestion)
                if renamed:
                    stats.renamed = True
                    stats.new_path = stats.path.parent / f"{stats.suggestion}.py"
                else:
                    stats.error = f"Rename failed: {error}"
            results.append(stats)

    return sorted(results, key=lambda s: s.path)


def report_stats(stats_list: list[FileStats], cwd: Path, apply: bool) -> None:
    """Log a summary of analysis and rename results via loguru."""
    meaningful = sum(1 for s in stats_list if s.has_meaning)
    unnamed = sum(1 for s in stats_list if not s.has_meaning)
    renamed = sum(1 for s in stats_list if s.renamed)
    errors = sum(1 for s in stats_list if s.error)
    mode = "APPLY" if apply else "DRY RUN"

    print("=" * 78)
    print(f"  Mode: {mode}")
    print(
        f"  Total files: {len(stats_list)} | Meaningful: {meaningful} | Unnamed: {unnamed}"
    )
    print(f"  Errors: {errors} | Renamed: {renamed}")
    print("=" * 78)

    if unnamed > 0:
        print("UNNAMED FILES:")
        for stats in stats_list:
            if not stats.has_meaning:
                try:
                    rel_path = stats.path.relative_to(cwd)
                except ValueError:
                    rel_path = stats.path
                print(f"  📄 {rel_path}")
                print(f"     Current: {stats.current_name}")
                if stats.suggestion:
                    print(f"     Suggest: {stats.suggestion}")
                else:
                    print("     Suggest: (no suggestion available)")
                if stats.error:
                    print(f"     Error:   {stats.error}")
                elif stats.renamed:
                    print(f"     ✓ Renamed to: {stats.suggestion}")

    if errors > 0:
        print("FILES WITH ERRORS:")
        for stats in stats_list:
            if stats.error:
                try:
                    rel_path = stats.path.relative_to(cwd)
                except ValueError:
                    rel_path = stats.path
                logger.error(f"  ❌ {rel_path}")
                logger.error(f"     {stats.error}")


def main() -> int:
    """Parse CLI arguments, run the analysis, and report results."""
    parser = argparse.ArgumentParser(
        description="Analyze Python files and suggest meaningful filenames",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python script.py
  python script.py . /path/to/project
  python script.py -a
  python script.py file1.py file2.py -a
        """,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[Path(".")],
        help="Files or directories to analyze (default: current directory)",
    )
    parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Apply suggestions and rename files in place",
    )
    args = parser.parse_args()

    try:
        cwd = Path.cwd()
        results = process_files(args.paths, apply=args.apply)
        if results:
            report_stats(results, cwd, args.apply)
        else:
            logger.warning("No Python files found.")
            return 1
    except Exception as e:
        logger.exception(f"Error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
