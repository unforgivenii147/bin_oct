#!/data/data/com.termux/files/home/.local/bin/python
"""Minify HTML files in place using minify-html (default backend), with
support for additional backends, multiple multiprocessing pool strategies,
and recursive directory input.

Usage examples:
    python minify_html_cli.py                       # process CWD recursively
    python minify_html_cli.py file.html dir/         # mix of files and dirs
    python minify_html_cli.py -b minify-html         # explicit backend
    python minify_html_cli.py --pool-method starmap  # explicit pool method
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
from collections.abc import Callable, Generator, Iterable
from pathlib import Path

import minify_html as mh

# --------------------------------------------------------------------------
# Backend registry
# --------------------------------------------------------------------------
# Each backend is a callable taking the original HTML string and returning
# the minified HTML string. Registered here so new backends (e.g. htmlmin)
# can be added without touching the rest of the script.


def _minify_html_backend(data: str) -> str:
    """Backend using the Rust-based `minify-html` library (fast, default)."""
    return mh.minify(data)


BACKENDS: dict[str, Callable[[str], str]] = {
    "minify-html": _minify_html_backend,
}
DEFAULT_BACKEND: str = "minify-html"

# --------------------------------------------------------------------------
# Pool method registry
# --------------------------------------------------------------------------
# Maps a CLI-selectable name to the mp.Pool method used to dispatch work.
# "imap_unordered" is the default: it streams results back as soon as any
# worker finishes, without waiting for the whole batch or preserving order,
# which is ideal for independent, I/O-bound per-file tasks like this one.

POOL_METHODS: tuple[str, ...] = ("map", "starmap", "apply_async", "imap_unordered")
DEFAULT_POOL_METHOD: str = "imap_unordered"


def process_file(path: Path, backend: str) -> tuple[str, bool, str]:
    """Minify a single HTML file in place using the given backend.

    Reads the file, runs it through the selected backend, and writes the
    result back only if it differs from the original (avoids unnecessary
    disk writes and mtime churn).

    Args:
        path: File to process.
        backend: Key into BACKENDS selecting the minifier implementation.

    Returns:
        (relative_path, changed, error_message). `error_message` is empty
        on success; `changed` is True only if the file was rewritten.
    """
    rel = str(path)
    minify_fn = BACKENDS[backend]
    try:
        data = path.read_text(encoding="utf-8")
    except OSError as e:
        return rel, False, f"read error: {e}"

    try:
        minified = minify_fn(data)
    except Exception as e:  # noqa: BLE001 - backend errors should not crash the pool
        return rel, False, f"minify error: {e}"

    if minified == data:
        return rel, False, ""

    try:
        path.write_text(minified, encoding="utf-8")
    except OSError as e:
        return rel, False, f"write error: {e}"

    return rel, True, ""


def iter_html_files(targets: Iterable[Path]) -> Generator[Path, None, None]:
    """Yield unique, resolved .html/.htm file paths from a mix of file and
    directory inputs. Directories are searched recursively.

    Deduplicates via a set of resolved paths so the same file reached
    through two different input arguments (e.g. a direct path and a parent
    directory) is only processed once.
    """
    seen: set[Path] = set()
    for target in targets:
        try:
            target = target.resolve()
        except OSError:
            continue
        if target.is_file():
            if target.suffix.lower() in (".html", ".htm") and target not in seen:
                seen.add(target)
                yield target
        elif target.is_dir():
            for ext in ("*.html", "*.htm"):
                for p in target.rglob(ext):
                    if p.is_file() and p not in seen:
                        seen.add(p)
                        yield p


def run_pool(
    files: list[Path],
    backend: str,
    pool_method: str,
    processes: int,
) -> Generator[tuple[str, bool, str], None, None]:
    """Dispatch `process_file` over `files` using the selected pool method.

    Each strategy behaves differently:
        map            - blocks, preserves order, returns all results at once.
        starmap        - like map, but unpacks (path, backend) tuples;
                          used here since process_file takes two arguments.
        apply_async    - non-blocking per-task submission; results are
                          collected via AsyncResult.get() as they complete.
        imap_unordered - lazy iterator, streams results as soon as any
                          worker finishes, order not preserved (default).

    Yields:
        (relative_path, changed, error_message) tuples, one per file.
    """
    with mp.Pool(processes=processes) as pool:
        if pool_method == "map":
            args_iter = ((f, backend) for f in files)
            # map only supports single-arg callables, so wrap via a small
            # lambda-free helper: use starmap semantics through a tuple
            # unpack in a thin wrapper instead of a lambda (picklable).
            results = pool.starmap(process_file, args_iter)
            yield from results

        elif pool_method == "starmap":
            args_iter = ((f, backend) for f in files)
            results = pool.starmap(process_file, args_iter)
            yield from results

        elif pool_method == "apply_async":
            async_results = [
                pool.apply_async(process_file, (f, backend)) for f in files
            ]
            for ar in async_results:
                yield ar.get()

        elif pool_method == "imap_unordered":
            args_iter = ((f, backend) for f in files)
            yield from (
                pool.starmap_async(process_file, args_iter).get()
                if False
                else pool.imap_unordered(_starmap_adapter(backend), files)
            )

        else:  # pragma: no cover - guarded by argparse choices
            raise ValueError(f"unknown pool method: {pool_method}")


def _starmap_adapter(backend: str) -> Callable[[Path], tuple[str, bool, str]]:
    """Build a single-argument callable binding `backend`, for use with
    `imap_unordered`, which only accepts single-argument functions.

    Uses functools.partial rather than a closure/lambda so the callable
    remains picklable across process boundaries.
    """
    from functools import partial

    return partial(process_file, backend=backend)


def parse_args() -> argparse.Namespace:
    """Define and parse command-line arguments."""
    ap = argparse.ArgumentParser(
        description="Minify HTML files in place using a pluggable backend.",
    )
    ap.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to process. Defaults to the current directory, recursively.",
    )
    ap.add_argument(
        "-b",
        "--backend",
        choices=sorted(BACKENDS),
        default=DEFAULT_BACKEND,
        help=f"Minifier backend to use (default: {DEFAULT_BACKEND}).",
    )
    ap.add_argument(
        "--pool-method",
        choices=POOL_METHODS,
        default=DEFAULT_POOL_METHOD,
        help=f"multiprocessing.Pool dispatch strategy (default: {DEFAULT_POOL_METHOD}).",
    )
    ap.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=mp.cpu_count(),
        help="Number of worker processes (default: CPU count).",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    targets: list[Path] = args.paths or [Path.cwd()]

    files = list(iter_html_files(targets))
    if not files:
        print("no HTML files found", file=sys.stderr)
        return 1

    changed_count = 0
    error_count = 0

    for rel, changed, err in run_pool(files, args.backend, args.pool_method, args.jobs):
        if err:
            error_count += 1
            print(f"{rel}: {err}", file=sys.stderr)
        elif changed:
            changed_count += 1
            print(f"{rel}: minified")

    print(
        f"\nDone: {changed_count}/{len(files)} file(s) minified, {error_count} error(s)."
    )
    return 0 if error_count == 0 else 2


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    raise SystemExit(main())
