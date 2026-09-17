#!/data/data/com.termux/files/home/.local/bin/python
"""
Recursive string search tool that walks a directory tree, searches filenames or file contents (including inside zip/tar archives), supports pause/resume via keyboard, and reports matches. Uses multiprocessing.Pool.apply_async with a fixed pool of 8 workers, loguru for logging, pathlib for paths, and full type hints.
"""

from __future__ import annotations

import argparse
import fnmatch
import tarfile
import threading
import zipfile
from collections.abc import Sequence
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path

from fastwalk import walk_files
from loguru import logger

pause_event: threading.Event = threading.Event()
pause_event.set()

DEFAULT_EXCLUDED_DIRS: set[str] = {".git"}
DEFAULT_SKIPPED_EXTS: set[str] = {".pyc", ".bak"}
ARCHIVE_EXTENSIONS: tuple[str, ...] = (
    ".tar.gz",
    ".tar",
    ".tar.xz",
    ".tar.zst",
    ".tar.bz2",
    ".zip",
    ".whl",
    ".apk",
)
WORKER_COUNT: int = 8

SearchResult = tuple[str, int | None]


def setup_keyboard_listener() -> bool:
    """Install a global keyboard listener to toggle pause/resume on space/p and c.

    Returns True if the listener was installed, False if the ``keyboard``
    package is unavailable.
    """
    try:
        import keyboard  # type: ignore[import-not-found]

        def on_key_press(event: keyboard.KeyboardEvent) -> None:  # type: ignore[name-defined]
            if event.name in {"space", "p"} and pause_event.is_set():
                pause_event.clear()
                print("PAUSED - press 'c' to continue...")
            elif event.name == "c" and not pause_event.is_set():
                pause_event.set()
                print("RESUMED - searching...")

        keyboard.on_press(on_key_press)
        return True
    except ImportError:
        logger.warning("'keyboard' not installed. Pause disabled.")
        return False


def is_excluded(
    path: Path,
    excluded_dirs: set[str],
    excluded_patterns: set[str],
) -> bool:
    """Return True if ``path`` lies under an excluded directory or matches an excluded glob."""
    for part in path.parts:
        if part in excluded_dirs:
            return True
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in excluded_patterns)


def should_skip_file(path: Path) -> bool:
    """Return True if the file's suffix is in the default skipped extensions."""
    return path.suffix in DEFAULT_SKIPPED_EXTS


def search_in_file(
    path: Path,
    search_string: str,
    search_content: bool,
) -> list[SearchResult]:
    """Search a single regular file for ``search_string``.

    When ``search_content`` is False, only the file name is checked; otherwise
    each line of the file is scanned. Returns a list of ``(path, line_or_None)``.
    """
    pause_event.wait()
    results: list[SearchResult] = []
    if not search_content:
        if search_string.lower() in path.name.lower():
            results.append((str(path), None))
        return results
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            for ln, line in enumerate(f, 1):
                pause_event.wait()
                if search_string in line:
                    results.append((str(path), ln))
    except Exception:
        pass
    return results


def extract_and_search_archive(
    archive_path: Path,
    search_string: str,
    search_content: bool,
) -> list[SearchResult]:
    """Search inside a zip/whl/apk or tar archive for ``search_string``.

    Matches archive member names when ``search_content`` is False, otherwise
    scans the decoded text of each member. Returns a list of
    ``("archive::member", line_or_None)`` tuples.
    """
    results: list[SearchResult] = []
    try:
        if archive_path.suffix == ".zip" or archive_path.name.endswith(
            (".whl", ".apk")
        ):
            with zipfile.ZipFile(archive_path) as zf:
                for member in zf.namelist():
                    pause_event.wait()
                    ref = f"{archive_path}::{member}"
                    if not search_content:
                        if search_string.lower() in member.lower():
                            results.append((ref, None))
                    else:
                        try:
                            content = zf.read(member).decode("utf-8", errors="ignore")
                            for ln, line in enumerate(content.splitlines(), 1):
                                if search_string in line:
                                    results.append((ref, ln))
                        except Exception:
                            pass
        else:
            with tarfile.open(archive_path, "r:*") as tf:
                for m in tf.getmembers():
                    pause_event.wait()
                    if not m.isfile():
                        continue
                    ref = f"{archive_path}::{m.name}"
                    if not search_content:
                        if search_string.lower() in m.name.lower():
                            results.append((ref, None))
                    else:
                        try:
                            f = tf.extractfile(m)
                            if f:
                                content = f.read().decode("utf-8", errors="ignore")
                                for ln, line in enumerate(content.splitlines(), 1):
                                    if search_string in line:
                                        results.append((ref, ln))
                        except Exception:
                            pass
    except Exception:
        pass
    return results


def process_file(
    path: Path,
    search_string: str,
    search_content: bool,
) -> list[SearchResult]:
    """Dispatch a single path to either archive or plain-file searching.

    Returns the list of matches so results can be aggregated by the caller.
    """
    path = Path(path)
    if path.name.endswith(ARCHIVE_EXTENSIONS):
        return extract_and_search_archive(path, search_string, search_content)
    return search_in_file(path, search_string, search_content)


def collect_files(
    root: Path,
    excluded_dirs: set[str],
    excluded_patterns: set[str],
) -> list[Path]:
    """Walk ``root`` and return all files that pass exclusion/skip filters."""
    files: list[Path] = []
    for pth in walk_files(root):
        path = Path(pth)
        if path.is_dir():
            continue
        if should_skip_file(path):
            continue
        if is_excluded(path, excluded_dirs, excluded_patterns):
            continue
        files.append(path)
    return files


def _report(results: Sequence[SearchResult]) -> int:
    """Log each result and return the count of newly reported matches."""
    for path, line_num in results:
        if line_num is not None:
            print(f"[FOUND] {path} (Line: {line_num})")
        else:
            print(f"[FOUND] {path}")
    return len(results)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Fast recursive string search")
    parser.add_argument("search_string")
    parser.add_argument("-c", "--content", action="store_true")
    parser.add_argument("-d", "--directory", default=".")
    parser.add_argument("-o", "--output", default="output")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Exclude dir or glob (repeatable)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: parse args, walk files, and search with a multiprocessing pool."""
    args = parse_args(argv)

    excluded_dirs: set[str] = DEFAULT_EXCLUDED_DIRS | {
        e for e in args.exclude if not any(ch in e for ch in "*?[]")
    }
    excluded_patterns: set[str] = {
        e for e in args.exclude if any(ch in e for ch in "*?[]")
    }

    setup_keyboard_listener()

    root = Path(args.directory).resolve()
    print(f"Root: {root}")
    print(f"Mode: {'content' if args.content else 'filename'}")
    print(f"Excluded dirs: {sorted(excluded_dirs)}")
    print(f"Excluded patterns: {sorted(excluded_patterns)}")
    print("-" * 40)

    files = collect_files(root, excluded_dirs, excluded_patterns)
    print(f"Files queued: {len(files)}")

    total: int = 0
    pool: Pool = Pool(processes=WORKER_COUNT)
    try:
        async_results: list[AsyncResult] = [
            pool.apply_async(process_file, (p, args.search_string, args.content))
            for p in files
        ]
        pool.close()
        for ar in async_results:
            try:
                results = ar.get()
            except Exception as exc:  # pragma: no cover - defensive
                logger.error(f"Worker failed: {exc}")
                continue
            total += _report(results)
    finally:
        pool.join()

    print(f"Total results: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
