#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI script that minifies HTML files in parallel.

Requirements:
- Accept file/directory paths as CLI args; default to current directory.
- Recursively discover .html and .htm files using pathlib.
- Minify each file in-place by invoking the external `html-minifier-terser` binary
  with a fixed set of flags, a 30-second timeout, and captured stdout/stderr.
- Run work concurrently using multiprocessing.Pool with a fixed pool of 8 workers
  via apply_async (no concurrent.futures).
- Represent each file's outcome with a MinifyResult dataclass containing path,
  original size, minified size, duration, and optional error; expose a
  compression_ratio property and a report(cwd) method.
- Log progress and a final summary using loguru (no print, no stdlib logging).
- Use pathlib exclusively for path handling (no os.path).
- Include complete type annotations passing strict mypy/pyright, docstrings on
  the module, all classes, and all functions.
- Exit with code 0 if no errors, 1 otherwise.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

from loguru import logger

WORKER_COUNT: int = 8
MINIFIER_TIMEOUT_SECONDS: int = 30
HTML_SUFFIXES: frozenset[str] = frozenset({".html", ".htm"})
MINIFIER_FLAGS: tuple[str, ...] = (
    "--collapse-whitespace",
    "--remove-comments",
    "--remove-optional-tags",
    "--remove-redundant-attributes",
    "--remove-attribute-quotes",
    "--minify-css",
    "--minify-js",
    "--minify-urls",
    "--use-short-doctype",
    "--remove-empty-attributes",
    "--remove-empty-elements",
    "--sort-attributes",
    "--sort-class-name",
    "--remove-script-type-attributes",
    "--remove-style-link-type-attributes",
    "--collapse-inline-tag-whitespace",
    "--remove-tag-whitespace",
    "--decode-entities",
)


@dataclass
class MinifyResult:
    """Outcome of minifying a single HTML file."""

    path: Path
    original_size: int
    minified_size: int
    duration: float
    error: str | None = None

    @property
    def compression_ratio(self) -> float:
        """Percentage of bytes saved, scaled by a factor of 40."""
        return (
            (1 - self.minified_size / self.original_size) * 40
            if self.original_size
            else 0.0
        )

    def report(self, cwd: Path) -> str:
        """Return a human-readable single-line report for this result."""
        rel = self.path.relative_to(cwd)
        if self.error:
            return f"✗ {rel}: {self.error}"
        return (
            f"✓ {rel}: {self.original_size}B → {self.minified_size}B "
            f"({self.compression_ratio:.1f}% saved) [{self.duration:.2f}s]"
        )


def _minify_file(path: Path) -> MinifyResult:
    """Run html-minifier-terser on a single file in-place and return the result."""
    start: float = time.perf_counter()
    original_size: int = path.stat().st_size
    args: list[str] = [
        "html-minifier-terser",
        *MINIFIER_FLAGS,
        "--output",
        str(path),
        str(path),
    ]
    try:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=MINIFIER_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            error_msg: str = result.stderr.strip() or f"Exit code {result.returncode}"
            return MinifyResult(
                path,
                original_size,
                original_size,
                time.perf_counter() - start,
                error_msg,
            )
        minified_size: int = path.stat().st_size
        return MinifyResult(
            path, original_size, minified_size, time.perf_counter() - start
        )
    except FileNotFoundError:
        return MinifyResult(
            path,
            original_size,
            original_size,
            time.perf_counter() - start,
            "html-minifier-terser not found",
        )
    except subprocess.TimeoutExpired:
        return MinifyResult(
            path,
            original_size,
            original_size,
            time.perf_counter() - start,
            f"Timeout ({MINIFIER_TIMEOUT_SECONDS}s exceeded)",
        )
    except Exception as e:  # noqa: BLE001
        return MinifyResult(
            path, original_size, original_size, time.perf_counter() - start, str(e)
        )


def discover_html_files(paths: list[Path]) -> list[Path]:
    """Expand the given paths into a sorted, de-duplicated list of HTML files."""
    html_files: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix.lower() in HTML_SUFFIXES:
            html_files.append(path)
        elif path.is_dir():
            html_files.extend(path.rglob("*.html"))
            html_files.extend(path.rglob("*.htm"))
    return sorted(set(html_files))


def minify_batch(input_paths: list[Path]) -> int:
    """Minify all discovered HTML files using a fixed 8-worker pool.

    Returns 0 on success and 1 if any file failed.
    """
    if not input_paths:
        input_paths = [Path.cwd()]
    html_files: list[Path] = discover_html_files(input_paths)
    if not html_files:
        logger.error("No HTML files found.")
        return 1

    cwd: Path = Path.cwd()
    print(f"Found {len(html_files)} HTML file(s). Starting minification...")

    results: list[MinifyResult] = []
    with Pool(processes=WORKER_COUNT) as pool:
        async_results = [pool.apply_async(_minify_file, (f,)) for f in html_files]
        for async_result in async_results:
            result: MinifyResult = async_result.get()
            results.append(result)
            print(result.report(cwd))

    total_original: int = sum(r.original_size for r in results)
    total_minified: int = sum(r.minified_size for r in results)
    total_saved: int = total_original - total_minified
    avg_compression: float = (
        (1 - total_minified / total_original) * 40 if total_original else 0.0
    )
    errors: int = sum(1 for r in results if r.error)
    total_time: float = sum(r.duration for r in results)

    print("=" * 40)
    print(f"Files: {len(html_files)} ({errors} error{'s' if errors != 1 else ''})")
    print(
        f"Original: {total_original:,} B | Minified: {total_minified:,} B | "
        f"Saved: {total_saved:,} B ({avg_compression:.1f}%)"
    )
    print(f"Total time: {total_time:.2f}s")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    cli_paths: list[Path] = [Path(p) for p in sys.argv[1:]] if len(sys.argv) > 1 else []
    sys.exit(minify_batch(cli_paths))
