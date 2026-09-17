#!/data/data/com.termux/files/home/.local/bin/python
"""Recursively find and execute all ``.py`` files in a directory in parallel.

Each Python file is executed in a separate process with a per-file timeout. The
tool uses a fixed :class:`multiprocessing.Pool` of 8 workers together with
:meth:`multiprocessing.pool.Pool.apply_async` and classifies any failures by
error type before printing a summary with :mod:`loguru`.

Example
-------
::

    python runner.py ./scripts --timeout 30 --verbose
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final

from loguru import logger

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

WORKER_COUNT: Final[int] = 8
DEFAULT_TIMEOUT: Final[float] = 30.0
FILE_PATTERN: Final[str] = "*.py"

# --------------------------------------------------------------------------- #
# Data structures
# --------------------------------------------------------------------------- #


class Outcome(str, Enum):
    """The possible outcomes of running a single Python file."""

    SUCCESS = "success"
    MODULE_NOT_FOUND = "ModuleNotFoundError"
    IMPORT_ERROR = "ImportError"
    SYNTAX_ERROR = "SyntaxError"
    ATTRIBUTE_ERROR = "AttributeError"
    TYPE_ERROR = "TypeError"
    VALUE_ERROR = "ValueError"
    KEYBOARD_INTERRUPT = "KeyboardInterrupt"
    TIMEOUT = "TimeoutError"
    OTHER_ERROR = "OtherError"


@dataclass(slots=True)
class FileResult:
    """The result of executing a single Python file.

    Attributes:
        path: The file that was executed.
        outcome: The classified outcome of the execution.
        returncode: The process return code, if the run completed.
        stderr: Captured standard error, if any.
        duration: Wall-clock duration of the run in seconds.
    """

    path: Path
    outcome: Outcome
    returncode: int | None = None
    stderr: str = ""
    duration: float = 0.0


@dataclass(slots=True)
class Summary:
    """Aggregated results across all executed files.

    Attributes:
        results: All individual :class:`FileResult` instances.
    """

    results: list[FileResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Return the total number of executed files."""
        return len(self.results)

    @property
    def succeeded(self) -> int:
        """Return the number of successfully executed files."""
        return sum(1 for r in self.results if r.outcome is Outcome.SUCCESS)

    @property
    def failed(self) -> int:
        """Return the number of files that failed for any reason."""
        return self.total - self.succeeded

    def counts_by_outcome(self) -> dict[Outcome, int]:
        """Return a mapping of outcome to occurrence count.

        Returns:
            A dictionary whose keys are :class:`Outcome` members and whose
            values are the number of files that produced that outcome.
        """
        counts: dict[Outcome, int] = {}
        for result in self.results:
            counts[result.outcome] = counts.get(result.outcome, 0) + 1
        return counts


# --------------------------------------------------------------------------- #
# Core logic
# --------------------------------------------------------------------------- #


def discover_python_files(directory: Path, recursive: bool) -> list[Path]:
    """Find all Python files under ``directory``.

    Args:
        directory: The root directory to search.
        recursive: If ``True``, descend into subdirectories.

    Returns:
        A sorted list of :class:`pathlib.Path` objects pointing to ``.py`` files.
    """
    if recursive:
        return sorted(p for p in directory.rglob(FILE_PATTERN) if p.is_file())
    return sorted(p for p in directory.glob(FILE_PATTERN) if p.is_file())


def _classify_failure(stderr: str, returncode: int) -> Outcome:
    """Map captured stderr to an :class:`Outcome`.

    Args:
        stderr: The captured standard error text.
        returncode: The process return code.

    Returns:
        The classified :class:`Outcome` for the failure.
    """
    # Order matters: more specific exceptions first.
    checks: tuple[tuple[str, Outcome], ...] = (
        ("ModuleNotFoundError", Outcome.MODULE_NOT_FOUND),
        ("ImportError", Outcome.IMPORT_ERROR),
        ("SyntaxError", Outcome.SYNTAX_ERROR),
        ("AttributeError", Outcome.ATTRIBUTE_ERROR),
        ("TypeError", Outcome.TYPE_ERROR),
        ("ValueError", Outcome.VALUE_ERROR),
    )
    for needle, outcome in checks:
        if needle in stderr:
            return outcome
    if "KeyboardInterrupt" in stderr or returncode in (-2, 130):
        return Outcome.KEYBOARD_INTERRUPT
    return Outcome.OTHER_ERROR


def run_file(path: Path, timeout: float) -> FileResult:
    """Execute a single Python file in a subprocess with a timeout.

    Args:
        path: The Python file to execute.
        timeout: Maximum wall-clock time in seconds.

    Returns:
        A :class:`FileResult` describing the outcome of the execution.
    """
    import time

    start = time.monotonic()
    try:
        completed = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return FileResult(
            path=path,
            outcome=Outcome.TIMEOUT,
            duration=time.monotonic() - start,
        )
    except KeyboardInterrupt:
        return FileResult(
            path=path,
            outcome=Outcome.KEYBOARD_INTERRUPT,
            duration=time.monotonic() - start,
        )

    duration = time.monotonic() - start
    if completed.returncode == 0:
        return FileResult(
            path=path,
            outcome=Outcome.SUCCESS,
            returncode=0,
            duration=duration,
        )

    outcome = _classify_failure(completed.stderr, completed.returncode)
    return FileResult(
        path=path,
        outcome=outcome,
        returncode=completed.returncode,
        stderr=completed.stderr.strip(),
        duration=duration,
    )


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def _log_result(result: FileResult, verbose: bool) -> None:
    """Log a single file result at an appropriate level.

    Args:
        result: The result to log.
        verbose: Whether verbose logging is enabled.
    """
    if result.outcome is Outcome.SUCCESS:
        if verbose:
            logger.success(f"OK   {result.path} ({result.duration:.2f}s)")
    else:
        logger.error(
            f"FAIL {result.path} -> {result.outcome.value} "
            f"(rc={result.returncode}, {result.duration:.2f}s)"
        )
        if verbose and result.stderr:
            logger.debug(f"{result.path} stderr:\n{result.stderr}")


def report_summary(summary: Summary) -> None:
    """Print a final summary of all executions.

    Args:
        summary: The aggregated :class:`Summary` to report.
    """
    print("=" * 60)
    print(
        f"Summary: {summary.total} file(s), "
        f"{summary.succeeded} succeeded, {summary.failed} failed"
    )
    counts = summary.counts_by_outcome()
    for outcome in Outcome:
        count = counts.get(outcome)
        if count:
            print(f"  {outcome.value:<22} {count}")
    print("=" * 60)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser.

    Returns:
        A configured :class:`argparse.ArgumentParser` instance.
    """
    parser = argparse.ArgumentParser(
        prog="pyrunner",
        description=(
            "Recursively find and execute all .py files in a directory "
            "with a per-file timeout, in parallel."
        ),
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Directory to search for Python files.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not descend into subdirectories.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Per-file timeout in seconds (default: {DEFAULT_TIMEOUT}).",
    )
    parser.add_argument(
        "--verbose",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable verbose logging (default: enabled).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the CLI tool.

    Args:
        argv: Optional argument vector; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code: ``0`` if all files succeeded, ``1`` otherwise.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    directory: Path = args.directory
    recursive: bool = not args.no_recursive
    timeout: float = args.timeout
    verbose: bool = args.verbose

    if not directory.is_dir():
        logger.error(f"Not a directory: {directory}")
        return 2

    files = discover_python_files(directory, recursive)
    if not files:
        logger.warning(f"No Python files found in {directory}")
        return 0

    print(
        f"Found {len(files)} Python file(s) in {directory} "
        f"(recursive={recursive}, timeout={timeout}s, workers={WORKER_COUNT})"
    )

    summary = Summary()
    try:
        with Pool(processes=WORKER_COUNT) as pool:
            pending: list[tuple[Path, AsyncResult[FileResult]]] = [
                (path, pool.apply_async(run_file, (path, timeout))) for path in files
            ]

            for path, async_result in pending:
                try:
                    result = async_result.get(timeout=timeout + 5.0)
                except Exception as exc:  # noqa: BLE001 - classify pool failures
                    result = FileResult(
                        path=path,
                        outcome=Outcome.OTHER_ERROR,
                        stderr=str(exc),
                    )
                summary.results.append(result)
                _log_result(result, verbose)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user; shutting down workers.")
        return 130

    report_summary(summary)
    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
