#!/data/data/com.termux/files/home/.local/bin/python

import argparse
import multiprocessing as mp
import re
import sys
from pathlib import Path
from typing import Iterator, Sequence

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Fixed pool size.  Deliberately *not* exposed on the command line — the
#: tool is designed for one-shot batch runs where tuning adds no value.
NUM_WORKERS: int = 8

#: Characters that may legally follow a backslash inside a Python string
#: literal.  Includes a trailing ``\n`` so that a physical line-continuation
#: is accepted.  Stored as a *raw* string so the character class below can
#: embed it verbatim.
_VALID_ESCAPE_FOLLOWERS: str = r"\\'\"abfnrtvNuUx0-7\n"

#: Matches an *unpaired* backslash that is followed by an invalid character.
#:
#: Group 1 captures an even run of already-escaped backslashes immediately
#: preceding the offending one, so :meth:`re.Pattern.sub` can re-emit them
#: unchanged.  ``(?<!\\)`` prevents matching in the middle of a run, and
#: ``(?:\\\\)*`` walks past every escaped pair.  The negative look-ahead
#: rejects all recognised escape introducers.
INVALID_ESCAPE_PATTERN: re.Pattern[str] = re.compile(
    r"((?<!\\)(?:\\\\)*)\\(?![" + _VALID_ESCAPE_FOLLOWERS + r"])"
)


# ---------------------------------------------------------------------------
# Per-file worker
# ---------------------------------------------------------------------------


def process_file(path: Path, autofix: bool = False) -> tuple[Path, int, bool]:
    """Inspect *path* for invalid escape sequences.

    Parameters
    ----------
    path:
        Source file to inspect.  Non-UTF-8 or unreadable files are reported
        as clean — a defensible default for a bulk-scanning tool that should
        not stop on a single bad input.
    autofix:
        If ``True``, rewrite the file in place, doubling every offending
        backslash.  Writes are best-effort: an ``OSError`` during the
        rewrite downgrades the result to "found but not fixed" instead of
        propagating.

    Returns
    -------
    tuple[Path, int, bool]
        ``(path, issue_count, was_rewritten)``.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return (path, 0, False)

    count = sum(1 for _ in INVALID_ESCAPE_PATTERN.finditer(content))
    if count == 0:
        return (path, 0, False)

    if not autofix:
        return (path, count, False)

    # ``\g<1>`` re-emits the escaped pairs; ``\\\\`` (raw) doubles the
    # offending backslash to ``\\`` in the target source.
    fixed = INVALID_ESCAPE_PATTERN.sub(r"\g<1>\\\\", content)
    try:
        path.write_text(fixed, encoding="utf-8")
    except OSError:
        return (path, count, False)
    return (path, count, True)


# ---------------------------------------------------------------------------
# Path discovery
# ---------------------------------------------------------------------------


def _iter_target_files(target: Path) -> Iterator[Path]:
    """Yield the ``*.py`` files covered by *target* (a file or directory)."""
    if target.is_file():
        if target.suffix == ".py":
            yield target
        return
    if target.is_dir():
        # ``rglob`` walks lazily; we filter before yielding so the caller
        # never sees directories that happen to end in ``.py``.
        for child in target.rglob("*.py"):
            if child.is_file():
                yield child


def discover_python_files(targets: Sequence[Path]) -> list[Path]:
    """Expand *targets* into a de-duplicated, order-preserving file list.

    Files reachable through more than one target (e.g. the same directory
    passed twice, or overlapping symlinked trees) are yielded only once —
    paths are compared by their resolved form so that aliases collapse
    cleanly.  Non-existent paths are reported on stderr and skipped.
    """
    seen: set[Path] = set()
    files: list[Path] = []

    for raw_target in targets:
        target = raw_target.expanduser()  # handles ``~`` / ``~user``
        if not target.exists():
            print(f"[SKIP] {raw_target}: path does not exist", file=sys.stderr)
            continue

        for candidate in _iter_target_files(target):
            try:
                key = candidate.resolve()
            except OSError:
                key = candidate  # broken symlink chain etc.
            if key in seen:
                continue
            seen.add(key)
            files.append(candidate)

    return files


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_escapes",
        description=(
            "Recursively scan Python files for invalid escape sequences "
            r"(for example '\d')."
        ),
    )
    parser.add_argument(
        "-a",
        "--autofix",
        action="store_true",
        help=(
            "Rewrite files, doubling invalid backslashes instead of only "
            "reporting them."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        metavar="PATH",
        help=(
            "Files and/or directories to scan.  Directories are searched "
            "recursively for *.py files.  Defaults to the current working "
            "directory when omitted."
        ),
    )
    return parser


def _display_path(path: Path) -> str:
    """Return *path* relative to the CWD when possible, else absolute."""
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.  Returns the process exit status."""
    args = build_parser().parse_args(argv)

    targets: list[Path] = list(args.paths) or [Path.cwd()]
    files = discover_python_files(targets)

    if not files:
        print("No Python files found.")
        return 0

    print(f"Scanning {len(files)} Python file(s) with {NUM_WORKERS} workers...\n")

    # Adaptive parallelism: skip the pool entirely when the workload is
    # smaller than the worker count — fork/join overhead would dominate.
    if len(files) >= NUM_WORKERS:
        # ``starmap`` fans the batch out in one shot and blocks until every
        # task finishes — no per-task ``AsyncResult`` bookkeeping required.
        with mp.Pool(processes=NUM_WORKERS) as pool:
            results: list[tuple[Path, int, bool]] = pool.starmap(
                process_file,
                ((path, args.autofix) for path in files),
            )
    else:
        results = [process_file(path, args.autofix) for path in files]

    total_issues = 0
    flagged_files = 0
    for path, count, fixed in results:
        if count == 0:
            continue
        flagged_files += 1
        total_issues += count
        status = "FIXED" if fixed else "FOUND"
        print(f"[{status}] {_display_path(path)}: {count} invalid escape sequence(s)")

    print("\n--- Summary ---")
    print(f"Files scanned:     {len(files)}")
    print(f"Files with issues: {flagged_files}")
    print(f"Total issues:      {total_issues}")

    if flagged_files and not args.autofix:
        print("\nRun with -a / --autofix to double-escape invalid backslashes.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
