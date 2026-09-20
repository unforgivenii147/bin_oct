#!/data/data/com.termux/files/home/.local/bin/python
"""
xb_extract.py — unified extractor for shell functions.

This module merges the two original scripts into a single pipeline with
flags that reproduce every behavior of both.

Original-script mapping
-----------------------
    xbash_functions.py   ->  python xb_extract.py --walker fastwalk --parallel \
                                                   --no-header --no-chmod
    xbash_functions2.py  ->  python xb_extract.py          # (all defaults)

Pipeline
--------
    1. Collect candidate shell scripts (.sh OR shebang scripts, unless
       --sh-only is given) from the inputs (files and/or directories).
    2. For each script, scan for function definitions of the form:
           name()   { ... }
           name     { ... }
           function name { ... }
       using brace-matching to find the closing '}'.
    3. Write each function to:
           <output>/<relative-dir-of-source>/<sanitized-name>[.sh]

Third-party dependencies
------------------------
    Optional: fastwalk  (only when --walker fastwalk is used)
    Optional: loguru    (only when --use-loguru is used)
Both are guarded with try/except and fall back to stdlib behavior.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import sys
from collections.abc import Iterable, Iterator
from multiprocessing import Pool
from pathlib import Path
from typing import Final, Protocol


# ---------------------------------------------------------------------------
# Constants (defaults match the original scripts)
# ---------------------------------------------------------------------------

EXCLUDED_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".py",
        ".h",
        ".c",
        ".js",
        ".ts",
        ".hpp",
        ".cpp",
        ".pyx",
        ".jsx",
        ".lua",
        ".tsx",
        ".pl",
        ".am",
        ".pm",
        ".syntax",
        ".so",
        ".rmeta",
    }
)

SHELL_SHEBANG_TOKENS: Final[tuple[str, ...]] = (
    "bash",
    "sh",
    "dash",
    "ksh",
    "zsh",
    "ash",
    "shell",
)

FUNCTION_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:function\s+)?(\w[\w\-]*)\s*(?:\(\))?\s*\{"
)

UNSAFE_NAME_RE: Final[re.Pattern[str]] = re.compile(r"[^\w\-]")

DEFAULT_MAX_FILE_SIZE: Final[int] = 1_000_000
DEFAULT_WORKERS: Final[int] = 8
DEFAULT_OUTPUT_DIR: Final[Path] = Path("extracted_functions")

IS_TERMUX: Final[bool] = (
    "TERMUX_VERSION" in os.environ or "com.termux" in os.environ.get("PREFIX", "")
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class _LoggerProtocol(Protocol):
    """Minimal logging interface used throughout the module."""

    def debug(self, msg: str, *args: object) -> None: ...
    def info(self, msg: str, *args: object) -> None: ...
    def warning(self, msg: str, *args: object) -> None: ...
    def error(self, msg: str, *args: object) -> None: ...


class _PrintLogger:
    """stdlib fallback logger using loguru-style '{}' formatting."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose

    def _emit(self, level: str, msg: str, args: tuple[object, ...]) -> None:
        text = msg.format(*args) if args else msg
        print(f"[{level}] {text}", file=sys.stderr)

    def debug(self, msg: str, *args: object) -> None:
        if self.verbose:
            self._emit("debug", msg, args)

    def info(self, msg: str, *args: object) -> None:
        self._emit("info", msg, args)

    def warning(self, msg: str, *args: object) -> None:
        self._emit("warn", msg, args)

    def error(self, msg: str, *args: object) -> None:
        self._emit("error", msg, args)


def make_logger(use_loguru: bool, verbose: bool) -> _LoggerProtocol:
    """Return a loguru logger if requested+available, else stdlib logger."""
    if use_loguru:
        try:
            from loguru import logger  # type: ignore
        except ImportError:
            print(
                "loguru is not installed; falling back to stdlib logger",
                file=sys.stderr,
            )
        else:
            logger.remove()
            logger.add(sys.stderr, level="DEBUG" if verbose else "INFO")
            return logger
    return _PrintLogger(verbose)


# ---------------------------------------------------------------------------
# File detection
# ---------------------------------------------------------------------------


def is_shell_script(
    path: Path,
    *,
    include_extensionless: bool = True,
    max_size: int = DEFAULT_MAX_FILE_SIZE,
) -> bool:
    """Return True if `path` looks like a shell script worth processing."""
    if not path.is_file():
        return False
    if path.suffix == ".sh":
        return True
    if not include_extensionless:
        return False
    try:
        if path.stat().st_size > max_size:
            return False
    except OSError:
        return False
    try:
        with open(path, "rb") as fh:
            head = fh.read(2)
            if b"\x00" in head:
                return False
            fh.seek(0)
            first_line = fh.readline().decode("utf-8", errors="ignore").strip()
    except (OSError, UnicodeDecodeError):
        return False
    if not first_line.startswith("#!"):
        return False
    lowered = first_line.lower()
    return any(tok in lowered for tok in SHELL_SHEBANG_TOKENS)


# ---------------------------------------------------------------------------
# Directory walking (two implementations, selected by --walker)
# ---------------------------------------------------------------------------


def _iter_directory_scandir(
    directory: Path,
    *,
    include_extensionless: bool,
    skip_hidden: bool,
    max_size: int,
    log: _LoggerProtocol,
) -> Iterator[Path]:
    try:
        with os.scandir(directory) as it:
            for entry in it:
                entry_path = Path(entry.path)
                if skip_hidden and entry_path.name.startswith("."):
                    continue
                try:
                    if entry.is_file():
                        if entry_path.suffix in EXCLUDED_SUFFIXES:
                            continue
                        if is_shell_script(
                            entry_path,
                            include_extensionless=include_extensionless,
                            max_size=max_size,
                        ):
                            yield entry_path.resolve()
                    elif entry.is_dir():
                        yield from _iter_directory_scandir(
                            entry_path,
                            include_extensionless=include_extensionless,
                            skip_hidden=skip_hidden,
                            max_size=max_size,
                            log=log,
                        )
                except OSError:
                    continue
    except PermissionError:
        log.warning("Permission denied accessing {}", directory)
    except OSError as exc:
        log.warning("OS error accessing {}: {}", directory, exc)


def collect_scripts_scandir(
    inputs: Iterable[Path],
    *,
    include_extensionless: bool,
    skip_hidden: bool,
    max_size: int,
    log: _LoggerProtocol,
) -> Iterator[Path]:
    """Generator-based walker using os.scandir (stdlib only)."""
    for p in inputs:
        if not p.exists():
            log.warning("{} does not exist, skipping...", p)
            continue
        if p.is_file():
            if is_shell_script(
                p, include_extensionless=include_extensionless, max_size=max_size
            ):
                yield p.resolve()
        elif p.is_dir():
            yield from _iter_directory_scandir(
                p,
                include_extensionless=include_extensionless,
                skip_hidden=skip_hidden,
                max_size=max_size,
                log=log,
            )
        else:
            log.warning("{} is not a file or directory, skipping...", p)


def collect_scripts_fastwalk(
    inputs: Iterable[Path],
    *,
    include_extensionless: bool,
    skip_hidden: bool,
    max_size: int,
    log: _LoggerProtocol,
) -> Iterator[Path]:
    """fastwalk-based walker (mirrors xbash_functions.py)."""
    try:
        from fastwalk import walk_files  # type: ignore
    except ImportError:
        log.error("fastwalk is not installed; falling back to scandir walker")
        yield from collect_scripts_scandir(
            inputs,
            include_extensionless=include_extensionless,
            skip_hidden=skip_hidden,
            max_size=max_size,
            log=log,
        )
        return

    for p in inputs:
        if not p.exists():
            log.warning("{} does not exist, skipping...", p)
            continue
        if p.is_file():
            if is_shell_script(
                p, include_extensionless=include_extensionless, max_size=max_size
            ):
                yield p.resolve()
        elif p.is_dir():
            for s in walk_files(p):
                t = Path(s)
                if skip_hidden:
                    try:
                        rel_parts = t.relative_to(p).parts
                    except ValueError:
                        rel_parts = t.parts
                    if any(part.startswith(".") for part in rel_parts):
                        continue
                if t.suffix in EXCLUDED_SUFFIXES:
                    continue
                if is_shell_script(
                    t, include_extensionless=include_extensionless, max_size=max_size
                ):
                    yield t.resolve()
        else:
            log.warning("{} is not a file or directory, skipping...", p)


def collect_scripts(
    inputs: Iterable[Path],
    *,
    walker: str,
    include_extensionless: bool,
    skip_hidden: bool,
    max_size: int,
    log: _LoggerProtocol,
) -> Iterator[Path]:
    """Dispatch to the requested walker and de-duplicate results."""
    gen = (
        collect_scripts_fastwalk(
            inputs,
            include_extensionless=include_extensionless,
            skip_hidden=skip_hidden,
            max_size=max_size,
            log=log,
        )
        if walker == "fastwalk"
        else collect_scripts_scandir(
            inputs,
            include_extensionless=include_extensionless,
            skip_hidden=skip_hidden,
            max_size=max_size,
            log=log,
        )
    )
    seen: set[Path] = set()
    for s in gen:
        if s not in seen:
            seen.add(s)
            yield s


# ---------------------------------------------------------------------------
# Function extraction
# ---------------------------------------------------------------------------


def extract_functions(path: Path, log: _LoggerProtocol) -> Iterator[tuple[str, str]]:
    """Yield (function_name, full_text_with_braces) for each function in `path`."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
    except OSError as exc:
        log.error("Error reading {}: {}", path, exc)
        return

    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = FUNCTION_RE.match(line)
        if not m:
            i += 1
            continue
        name = m.group(1)
        block = [line]
        depth = line.count("{") - line.count("}")
        j = i + 1
        while j < len(lines) and depth > 0:
            nxt = lines[j]
            block.append(nxt)
            depth += nxt.count("{") - nxt.count("}")
            j += 1
        if depth == 0:
            yield name, "\n".join(block)
        else:
            log.warning(
                "Could not find matching closing brace for function '{}' in {}",
                name,
                path,
            )
        i = j


# ---------------------------------------------------------------------------
# Writing output files
# ---------------------------------------------------------------------------


def write_function(
    name: str,
    body: str,
    source_path: Path,
    output_dir: Path,
    *,
    use_extension: bool,
    add_header: bool,
    log: _LoggerProtocol,
) -> Path | None:
    """Write one extracted function to disk; return target path or None on error."""
    safe_name = UNSAFE_NAME_RE.sub("_", name)
    try:
        rel = source_path.relative_to(Path.cwd())
    except ValueError:
        rel = source_path

    target_dir = output_dir / rel.parent
    filename = f"{safe_name}.sh" if use_extension else safe_name
    target = target_dir / filename
    target_dir.mkdir(parents=True, exist_ok=True)

    header = ""
    if add_header:
        header = (
            "#!/bin/bash\n"
            f"# Function: {name}\n"
            f"# Extracted from: {source_path}\n"
            f"# Original file: {source_path.name}\n"
            f"# Environment: {'Termux' if IS_TERMUX else 'Standard'}\n\n"
        )

    try:
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(header)
            fh.write(body)
            fh.write("\n")
    except OSError as exc:
        log.error("Error writing function '{}' to {}: {}", name, target, exc)
        return None
    return target


# ---------------------------------------------------------------------------
# Worker (used by multiprocessing.Pool)
# ---------------------------------------------------------------------------


def _process_one(
    task: tuple[Path, Path, bool, bool, bool, bool],
) -> tuple[Path, list[Path]]:
    """Extract all functions from one file. Must be top-level for pickling."""
    path, output_dir, use_extension, add_header, chmod_files, verbose = task
    log = _PrintLogger(verbose)
    written: list[Path] = []
    for name, body in extract_functions(path, log):
        target = write_function(
            name,
            body,
            path,
            output_dir,
            use_extension=use_extension,
            add_header=add_header,
            log=log,
        )
        if target is None:
            continue
        if chmod_files:
            with contextlib.suppress(OSError):
                target.chmod(target.stat().st_mode | 0o111)
        written.append(target)
    return path, written


# ---------------------------------------------------------------------------
# Top-level pipeline
# ---------------------------------------------------------------------------


def _process_scripts(
    scripts: list[Path], args: argparse.Namespace, log: _LoggerProtocol
) -> int:
    use_extension = not args.no_extension
    add_header = not args.no_header
    chmod_files = not args.no_chmod
    total = 0

    if args.parallel and len(scripts) > 1:
        print(f"Processing files in parallel with {args.workers} workers...")
        tasks = [
            (p, args.output, use_extension, add_header, chmod_files, args.verbose)
            for p in scripts
        ]
        with Pool(processes=args.workers) as pool:
            for path, written in pool.imap_unordered(_process_one, tasks):
                total += len(written)
                if args.verbose or written:
                    print(f"  {path}: extracted {len(written)} function(s)")
    else:
        print("Processing files sequentially...")
        for p in sorted(scripts):
            _, written = _process_one(
                (p, args.output, use_extension, add_header, chmod_files, args.verbose)
            )
            total += len(written)
            if args.verbose or written:
                print(f"  {p}: extracted {len(written)} function(s)")
    return total


def run(args: argparse.Namespace) -> int:
    """Execute the full pipeline for parsed CLI args."""
    log = make_logger(args.use_loguru, args.verbose)

    if IS_TERMUX:
        print(f"Running in Termux environment (workers={args.workers})")

    inputs: list[Path] = args.inputs or [Path(".")]
    include_extensionless = not args.sh_only

    print("Searching for shell scripts...")
    scripts = list(
        collect_scripts(
            inputs,
            walker=args.walker,
            include_extensionless=include_extensionless,
            skip_hidden=args.skip_hidden,
            max_size=args.max_size,
            log=log,
        )
    )

    if not scripts:
        print("No shell scripts found to process.")
        if not args.sh_only:
            print("Tip: Use --sh-only to only process .sh files")
        return 0

    print(f"Found {len(scripts)} shell script(s) to process.")
    if args.verbose:
        for s in sorted(scripts):
            log.debug("  - {}", s)

    if args.dry_run:
        print(f"\nDry run — would extract to: {args.output.absolute()}")
        return 0

    try:
        args.output.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        log.error(
            "Cannot create output directory '{}'. Check permissions.", args.output
        )
        return 1

    total = _process_scripts(scripts, args, log)

    print(f"\nDone! Extracted {total} function(s) to '{args.output.absolute()}'")

    if IS_TERMUX:
        with contextlib.suppress(BaseException):
            args.output.chmod(args.output.stat().st_mode | 0o755)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xb_extract",
        description=(
            "Extract shell function definitions from .sh files and extensionless "
            "shell scripts into individual files. Merged behavior of "
            "xbash_functions.py and xbash_functions2.py."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Original script equivalents:\n"
            "  xbash_functions.py   ->  python xb_extract.py --walker fastwalk "
            "--parallel --no-header --no-chmod\n"
            "  xbash_functions2.py  ->  python xb_extract.py\n\n"
            "Examples:\n"
            "  # Process all shell scripts in the current directory (defaults)\n"
            "  %(prog)s\n\n"
            "  # Specific files/directories with a custom output dir\n"
            "  %(prog)s script1.sh myscript dir1/ dir2/ -o out_functions\n\n"
            "  # Only .sh files, skip hidden, dry run\n"
            "  %(prog)s --sh-only --skip-hidden --dry-run\n\n"
            "  # Parallel extraction using fastwalk walker (script1 behavior)\n"
            "  %(prog)s --walker fastwalk --parallel --no-header --no-chmod\n"
        ),
    )
    p.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="Files and/or directories to process. If none provided, the "
        "current directory is used recursively.",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for extracted functions "
        f"(default: {DEFAULT_OUTPUT_DIR}).",
    )
    p.add_argument(
        "--sh-only",
        action="store_true",
        help="Only process files with a .sh extension (ignore extensionless scripts).",
    )
    p.add_argument(
        "--no-extension",
        action="store_true",
        help="Write extracted functions without a .sh extension.",
    )
    p.add_argument(
        "--no-header",
        action="store_true",
        help="Do NOT prepend the '#!/bin/bash' + metadata header "
        "(xbash_functions.py behavior).",
    )
    p.add_argument(
        "--no-chmod",
        action="store_true",
        help="Do NOT make output files executable "
        "(xbash_functions.py does not chmod files).",
    )
    p.add_argument(
        "--skip-hidden",
        action="store_true",
        help="Skip hidden files and directories (names starting with '.').",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List scripts that would be processed and exit.",
    )
    p.add_argument(
        "--walker",
        choices=("scandir", "fastwalk"),
        default="scandir",
        help="Filesystem walker: 'scandir' (stdlib, default) or 'fastwalk' "
        "(requires the fastwalk package; falls back to scandir).",
    )
    p.add_argument(
        "--parallel",
        action="store_true",
        help="Use multiprocessing.Pool for file processing (xbash_functions.py "
        "behavior). Default is sequential.",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Number of worker processes for --parallel (default: {DEFAULT_WORKERS}).",
    )
    p.add_argument(
        "--max-size",
        type=int,
        default=DEFAULT_MAX_FILE_SIZE,
        help=f"Maximum size (bytes) for extensionless-script detection "
        f"(default: {DEFAULT_MAX_FILE_SIZE}).",
    )
    p.add_argument(
        "--use-loguru",
        action="store_true",
        help="Use loguru for logging if installed (xbash_functions.py behavior). "
        "Falls back to stdlib logging otherwise.",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output (debug level, per-file details).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting...", file=sys.stderr)
        sys.exit(1)
