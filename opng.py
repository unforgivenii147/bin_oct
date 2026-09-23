#!/data/data/com.termux/files/home/.local/bin/python
"""Optimize ``.png`` files in place by shelling out to ``optipng``.

The script discovers PNG files (case-insensitively) under the paths supplied
on the command line, runs ``optipng`` on each of them through a bounded
``multiprocessing.Pool``, validates the result, and — only when the result is
a well-formed PNG, not byte-identical, and strictly smaller — atomically
replaces the original.

Design highlights
-----------------
* Discovery uses the Rust ``fastwalk`` extension (``walk_files``). Because
  that helper exposes no pruning hooks, every filter (``SKIP_DIRS``,
  case-insensitive ``PNG_SUFFIXES``, symlinks, deduplication) is applied in
  Python on the returned list.
* ``optipng`` edits files in place, so the worker first makes a sibling copy
  of the input under a temporary name, runs ``optipng`` on the copy, and
  only then swaps it in via ``os.replace``. The original mode bits are
  preserved.
* Every file is processed in a worker process; the parent prints each
  worker's captured ``optipng`` stdout/stderr verbatim, so lines never
  interleave across workers.
* Failures never propagate out of a worker: they are reported through the
  ``error`` field of :class:`ProcessResult`.
* A non-zero exit code from ``main`` signals that at least one file errored.

External requirements: the ``fastwalk`` extension module and the
``optipng`` CLI (or a compatible path supplied via ``--optipng``).
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from functools import partial
from multiprocessing import Pool
from pathlib import Path
from typing import Final, Iterator, NamedTuple, Sequence

from fastwalk import walk_files

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

#: Directory names that are pruned during discovery. Because ``walk_files``
#: cannot prune on the Rust side, the filter is enforced here in Python on
#: the paths it returns.
SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".tox",
        ".nox",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        "node_modules",
        ".cache",
        ".idea",
        ".vscode",
        "build",
        "dist",
        "target",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)

#: Accepted PNG suffixes, all lower-case. Matching is done on
#: ``path.suffix.lower()`` so ``.png``, ``.PNG`` and ``.Png`` all qualify.
#: Extend this set to recognise further extensions.
PNG_SUFFIXES: Final[frozenset[str]] = frozenset({".png"})

#: The 8-byte PNG signature. Every valid PNG file starts with these bytes
#: (see PNG specification § 5.2). Used as the "well-formed" check.
PNG_MAGIC: Final[bytes] = b"\x89PNG\r\n\x1a\n"

#: Slice size used when iterating the list returned by ``walk_files``.
WALK_CHUNK: Final[int] = 512

#: Fixed size of the worker pool (no CLI flag by design).
DEFAULT_WORKERS: Final[int] = 8

#: ``imap_unordered`` chunksize; small enough to keep the parent responsive.
IMAP_CHUNKSIZE: Final[int] = 4

#: Default per-file optipng timeout, in seconds.
DEFAULT_TIMEOUT: Final[float] = 300.0

#: Chunk size used for the streaming byte-identity comparison.
COMPARE_CHUNK: Final[int] = 1 << 16

#: Default optimization level for ``optipng -o`` (1 = fast, 7 = best).
DEFAULT_OPT_LEVEL: Final[int] = 7

#: Valid optimization levels accepted by ``optipng -o``.
OPT_LEVELS: Final[range] = range(1, 8)

#: optipng's exit code for a successful run (any non-zero is treated as an
#: error). Unlike pngquant, optipng has no distinct "already optimal" code:
#: when it decides nothing can be improved it simply leaves the file alone
#: and still exits 0.
OPTIPNG_SUCCESS: Final[int] = 0


# --------------------------------------------------------------------------- #
# Result record
# --------------------------------------------------------------------------- #


class ProcessResult(NamedTuple):
    """Outcome of processing a single PNG file.

    Attributes
    ----------
    path:
        The path as the parent discovered it (may be relative).
    original_size:
        Size of the original file in bytes, or ``0`` when it could not be
        determined.
    new_size:
        Size of optipng's output in bytes, or ``0`` when no output was
        produced.
    stdout:
        Decoded stdout of the optipng subprocess (UTF-8, ``errors="replace"``).
    stderr:
        Decoded stderr of the optipng subprocess (UTF-8, ``errors="replace"``).
    skipped:
        ``True`` when the original was preserved because the output was not
        strictly smaller (larger, or same size with different bytes).
    no_change:
        ``True`` when the output was byte-identical to the input; no write
        was performed and no mtime was bumped.
    error:
        Short, human-readable error message, or ``None`` on success.
    """

    path: Path
    original_size: int
    new_size: int
    stdout: str
    stderr: str
    skipped: bool
    no_change: bool
    error: str | None


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #


def format_bytes(n: int) -> str:
    """Return a human-readable byte count using B/KiB/MiB/GiB/TiB units."""
    sign = "-" if n < 0 else ""
    value = float(abs(n))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024.0 or unit == "TiB":
            if unit == "B":
                return f"{sign}{int(value)} B"
            return f"{sign}{value:.2f} {unit}"
        value /= 1024.0
    # Unreachable, but keeps static analysers happy.
    return f"{sign}{value:.2f} TiB"


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


def _dedupe(path: Path, seen: set[Path]) -> bool:
    """Return ``True`` if *path* is new, registering its resolved key."""
    try:
        key = path.resolve()
    except OSError:
        # ``resolve`` can fail on weird filesystems; fall back to the raw path
        # so we still avoid processing an obviously repeated entry.
        key = path
    if key in seen:
        return False
    seen.add(key)
    return True


def _iter_directory(root: Path, seen: set[Path]) -> Iterator[Path]:
    """Yield PNG files under a single directory *root*.

    ``walk_files`` returns a complete ``list[Path]`` for the root; the list is
    consumed in ``WALK_CHUNK``-sized slices so the parent's peak allocation
    stays modest even for very large trees. Filters are applied cheapest
    first: suffix, then skip-dir, then ``lstat`` (symlink), then ``resolve``.
    """
    try:
        found = walk_files(str(root))
    except Exception as exc:  # noqa: BLE001 - surface as a warning, keep going
        print(f"warning: walk_files failed for {root}: {exc}", file=sys.stderr)
        return

    for start in range(0, len(found), WALK_CHUNK):
        for entry in found[start : start + WALK_CHUNK]:
            path = Path(entry)

            # Cheap: extension check (case-insensitive).
            if path.suffix.lower() not in PNG_SUFFIXES:
                continue

            # Cheap: prune anything inside a SKIP_DIRS component.
            try:
                rel = path.relative_to(root)
            except ValueError:
                rel = path
            if any(part in SKIP_DIRS for part in rel.parts[:-1]):
                continue

            # Expensive: never touch symlinks found during the walk.
            try:
                if path.is_symlink():
                    continue
            except OSError:
                continue

            # Expensive: dedupe via resolve().
            if not _dedupe(path, seen):
                continue

            yield path


def iter_png_files(roots: Sequence[Path]) -> Iterator[Path]:
    """Yield deduplicated PNG files discovered under *roots*.

    Explicit files are accepted (subject to the PNG-suffix filter and the
    symlink policy); directories are walked recursively with ``fastwalk``.
    Per-root problems (missing paths, walk failures) are reported as
    warnings on stderr and do not abort the run.
    """
    seen: set[Path] = set()

    for raw_root in roots:
        try:
            if not raw_root.exists():
                print(
                    f"warning: path does not exist: {raw_root}",
                    file=sys.stderr,
                )
                continue

            if raw_root.is_file():
                # Never process a symlinked file: optipng would read the
                # target but os.replace would then clobber the link itself.
                if raw_root.is_symlink():
                    print(
                        f"warning: skipping symlink: {raw_root}",
                        file=sys.stderr,
                    )
                    continue
                if raw_root.suffix.lower() in PNG_SUFFIXES and _dedupe(raw_root, seen):
                    yield raw_root
                continue

            if raw_root.is_dir():
                # Explicit directory roots may be symlinks; the user asked
                # for them, so follow the link and walk the real directory.
                # Symlinks *inside* the walk are still skipped.
                try:
                    root = raw_root.resolve()
                except OSError as exc:
                    print(
                        f"warning: cannot resolve {raw_root}: {exc}",
                        file=sys.stderr,
                    )
                    continue
                yield from _iter_directory(root, seen)
                continue

            print(
                f"warning: not a file or directory: {raw_root}",
                file=sys.stderr,
            )
        except OSError as exc:
            print(
                f"warning: cannot inspect {raw_root}: {exc}",
                file=sys.stderr,
            )


# --------------------------------------------------------------------------- #
# Worker
# --------------------------------------------------------------------------- #


def _files_identical(a: Path, b: Path, a_size: int, b_size: int) -> bool:
    """Return ``True`` iff *a* and *b* have byte-identical contents.

    The size check runs first as a fast reject; otherwise both files are
    streamed in ``COMPARE_CHUNK``-sized blocks.
    """
    if a_size != b_size:
        return False
    with a.open("rb") as fa, b.open("rb") as fb:
        while True:
            chunk_a = fa.read(COMPARE_CHUNK)
            chunk_b = fb.read(COMPARE_CHUNK)
            if chunk_a != chunk_b:
                return False
            if not chunk_a:
                return True


def _is_valid_png(path: Path) -> tuple[bool, str | None]:
    """Return ``(ok, error)`` for the PNG magic-byte check.

    The full PNG structure (chunks, CRC) is not validated — optipng is
    trusted to write a valid file and the signature catches the realistic
    failure modes (empty output, truncated write, plain text error dumped
    into the output file).
    """
    try:
        with path.open("rb") as f:
            header = f.read(len(PNG_MAGIC))
    except OSError as exc:
        return False, f"cannot read output: {exc}"
    if header != PNG_MAGIC:
        return False, "output is not a PNG (bad signature)"
    return True, None


def process_file(
    path: Path,
    *,
    optipng: str,
    opt_level: int,
    extra_args: Sequence[str],
    strip: bool,
    timeout: float,
    dry_run: bool,
) -> ProcessResult:
    """Run optipng on a single PNG and (optionally) replace it atomically.

    optipng edits files in place, so we stage the input as a sibling temp
    copy, run optipng against the copy, and only swap it in when the result
    passes every validation gate.

    This function never raises: every failure — a missing executable, a
    timeout, a bad signature, a failed ``os.replace`` — is turned into an
    entry on the returned :class:`ProcessResult`.
    """
    # --- Resolve symlinks so os.replace targets the real file. ------------
    # Discovery normally filters symlinks, but hardlinks / bind mounts /
    # unusual setups can bypass that filter; resolving here is defensive.
    try:
        target = path.resolve(strict=True)
    except OSError as exc:
        return ProcessResult(path, 0, 0, "", "", False, False, f"cannot resolve: {exc}")

    # --- Snapshot original size and mode bits. ----------------------------
    try:
        st = target.stat()
    except OSError as exc:
        return ProcessResult(path, 0, 0, "", "", False, False, f"cannot stat: {exc}")
    original_size = st.st_size
    original_mode = stat.S_IMODE(st.st_mode)

    tmp_path: Path | None = None
    try:
        # --- Allocate a sibling temp file. --------------------------------
        # Derive the suffix from the target's original extension so a
        # ``logo.PNG`` produces ``logo.<rand>.PNG.tmp`` — cosmetic, but it
        # makes in-progress directory listings self-explanatory.
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=target.stem + ".",
                suffix=target.suffix + ".tmp",
                dir=str(target.parent),
            )
            try:
                os.close(fd)
            except OSError:
                pass
            tmp_path = Path(tmp_name)
        except OSError as exc:
            return ProcessResult(
                path,
                original_size,
                0,
                "",
                "",
                False,
                False,
                f"cannot create temp file: {exc}",
            )

        # --- Stage the input as a working copy for optipng. ---------------
        # ``copy2`` preserves mode bits and mtime; optipng then rewrites the
        # copy in place. If it decides nothing can be improved, the copy
        # stays byte-identical and we detect that below.
        try:
            shutil.copy2(target, tmp_path)
        except OSError as exc:
            return ProcessResult(
                path,
                original_size,
                0,
                "",
                "",
                False,
                False,
                f"cannot stage temp copy: {exc}",
            )

        # --- Build and run the optipng command. ---------------------------
        # optipng syntax: ``optipng [options] file...``. The ``-o`` flag
        # selects the optimization level (1..7). ``--`` terminates option
        # parsing so a path beginning with ``-`` stays positional.
        cmd: list[str] = [optipng, "-o", str(opt_level)]
        if strip:
            cmd += ["-strip", "all"]
        cmd.extend(extra_args)
        cmd.append("--")
        cmd.append(str(tmp_path))

        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ProcessResult(
                path,
                original_size,
                0,
                "",
                "",
                False,
                False,
                f"optipng timed out after {timeout:g}s",
            )
        except FileNotFoundError:
            return ProcessResult(
                path,
                original_size,
                0,
                "",
                "",
                False,
                False,
                f"optipng executable not found: {optipng!r}",
            )
        except OSError as exc:
            return ProcessResult(
                path,
                original_size,
                0,
                "",
                "",
                False,
                False,
                f"failed to run optipng: {exc}",
            )

        stdout = completed.stdout.decode("utf-8", errors="replace")
        stderr = completed.stderr.decode("utf-8", errors="replace")

        if completed.returncode != OPTIPNG_SUCCESS:
            return ProcessResult(
                path,
                original_size,
                0,
                stdout,
                stderr,
                False,
                False,
                f"optipng exited with status {completed.returncode}",
            )

        # --- Validate optipng's output. -----------------------------------
        try:
            new_size = tmp_path.stat().st_size
        except OSError as exc:
            return ProcessResult(
                path,
                original_size,
                0,
                stdout,
                stderr,
                False,
                False,
                f"optipng produced no output: {exc}",
            )

        if new_size == 0:
            return ProcessResult(
                path,
                original_size,
                0,
                stdout,
                stderr,
                False,
                False,
                "optipng produced an empty file",
            )

        ok, sig_err = _is_valid_png(tmp_path)
        if not ok:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                False,
                False,
                sig_err,
            )

        # --- Byte-identity short-circuit (runs before the size compare). --
        # When optipng decides the file is already optimal it leaves the
        # working copy untouched, so this branch is the normal "nothing to
        # do" path.
        try:
            identical = _files_identical(target, tmp_path, original_size, new_size)
        except OSError as exc:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                False,
                False,
                f"cannot compare files: {exc}",
            )

        if identical:
            # No write at all: no inode churn, no mtime bump.
            return ProcessResult(
                path,
                original_size,
                original_size,
                stdout,
                stderr,
                False,
                True,
                None,
            )

        # --- Output larger than input: keep the original. -----------------
        if new_size > original_size:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                True,
                False,
                None,
            )

        # --- Same size but different bytes: keep the original. ------------
        if new_size == original_size:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                True,
                False,
                None,
            )

        # --- Strictly smaller: this is the only path that writes. ---------
        if dry_run:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                False,
                False,
                None,
            )

        try:
            os.chmod(tmp_path, original_mode)
            os.replace(tmp_path, target)
        except OSError as exc:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                False,
                False,
                f"failed to replace original: {exc}",
            )

        # Ownership of the temp file has moved to ``target``.
        tmp_path = None
        return ProcessResult(
            path,
            original_size,
            new_size,
            stdout,
            stderr,
            False,
            False,
            None,
        )

    finally:
        # Per-file cleanup; a failure here must never mask the real result.
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# Classification & reporting
# --------------------------------------------------------------------------- #


def _classify(result: ProcessResult, dry_run: bool) -> str:
    """Map a :class:`ProcessResult` onto one of the reporting tags."""
    if result.error is not None:
        return "ERROR"
    if result.no_change:
        return "NOCHG"
    if result.skipped:
        # ``skipped`` covers both "larger" (SKIP) and "same size, different
        # bytes" (SAME); the size delta distinguishes them.
        return "SAME" if result.new_size == result.original_size else "SKIP"
    if dry_run:
        return "DRY-RUN"
    return "OK"


def _emit_optipng_output(result: ProcessResult) -> None:
    """Write the worker-captured optipng streams to our own streams."""
    if result.stdout:
        sys.stdout.write(result.stdout)
        if not result.stdout.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
    if result.stderr:
        sys.stderr.write(result.stderr)
        if not result.stderr.endswith("\n"):
            sys.stderr.write("\n")
        sys.stderr.flush()


def _print_status(result: ProcessResult, tag: str) -> None:
    """Print a single, human-readable status line for *result*."""
    path = result.path
    orig = result.original_size
    new = result.new_size

    if tag == "OK":
        saved = orig - new
        pct = (saved / orig * 100.0) if orig else 0.0
        print(
            f"[OK]      {path}  "
            f"{format_bytes(orig)} -> {format_bytes(new)}  "
            f"(-{format_bytes(saved)}, -{pct:.1f}%)"
        )
    elif tag == "DRY-RUN":
        saved = orig - new
        pct = (saved / orig * 100.0) if orig else 0.0
        print(
            f"[DRY-RUN] {path}  "
            f"{format_bytes(orig)} -> {format_bytes(new)}  "
            f"(would save {format_bytes(saved)}, {pct:.1f}%)"
        )
    elif tag == "NOCHG":
        print(f"[NOCHG]   {path}  {format_bytes(orig)}  (byte-identical)")
    elif tag == "SAME":
        print(f"[SAME]    {path}  {format_bytes(orig)}  (same size, different bytes)")
    elif tag == "SKIP":
        growth = new - orig
        print(
            f"[SKIP]    {path}  "
            f"{format_bytes(orig)} -> {format_bytes(new)}  "
            f"(larger by {format_bytes(growth)})"
        )
    else:  # ERROR
        print(f"[ERROR]   {path}  {result.error}", file=sys.stderr)


def _print_summary(
    counters: dict[str, int], total_before: int, total_after: int
) -> None:
    """Print the final aggregate report."""
    total = sum(counters.values())
    skipped = counters["SAME"] + counters["SKIP"]

    print()
    print("-" * 66)
    print("Summary")
    print("-" * 66)
    print(f"  Processed : {total}")
    print(f"  Changed   : {counters['OK']}")
    if counters["DRY-RUN"]:
        print(f"  Dry-run   : {counters['DRY-RUN']}")
    print(f"  Unchanged : {counters['NOCHG']}")
    print(f"  Skipped   : {skipped}")
    if skipped:
        print(f"      same-size-different-bytes : {counters['SAME']}")
        print(f"      larger-output             : {counters['SKIP']}")
    print(f"  Errored   : {counters['ERROR']}")

    if total_before:
        saved = total_before - total_after
        pct = (saved / total_before * 100.0) if total_before else 0.0
        print()
        print(
            f"  Bytes     : {format_bytes(total_before)} -> "
            f"{format_bytes(total_after)}  "
            f"(saved {format_bytes(saved)}, {pct:.1f}%)"
        )
    else:
        print()
        print("  Bytes     : no size changes")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser."""
    parser = argparse.ArgumentParser(
        prog="optipng-optimize",
        description=(
            "Optimize PNG files in place using optipng. "
            "With no paths, the current directory is walked recursively."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="Files or directories to process (default: current directory).",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Do not print optipng's own stdout/stderr; only summary lines.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run and validate, but do not modify any files.",
    )
    parser.add_argument(
        "-o",
        dest="opt_level",
        type=int,
        choices=OPT_LEVELS,
        default=DEFAULT_OPT_LEVEL,
        metavar="1-7",
        help=(
            "optipng optimization level (-o), 1 (fastest) to 7 (best). "
            f"Default: {DEFAULT_OPT_LEVEL}."
        ),
    )
    parser.add_argument(
        "--strip",
        action="store_true",
        help="Pass '-strip all' to optipng to remove ancillary chunks.",
    )
    parser.add_argument(
        "--optipng",
        default="optipng",
        metavar="PATH",
        help="Path to the optipng executable (default: search PATH).",
    )
    parser.add_argument(
        "--optipng-arg",
        action="append",
        default=[],
        metavar="ARG",
        help="Extra argument to pass to optipng; may be repeated.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help=f"Per-file optipng timeout (default: {DEFAULT_TIMEOUT:g}s).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Program entry point. Returns a non-zero status if any file errored."""
    args = _build_parser().parse_args(argv)

    roots = [Path(p) for p in args.paths] if args.paths else [Path(".")]

    # Bind the worker options with functools.partial so ``process_file``
    # stays a top-level, picklable function.
    worker = partial(
        process_file,
        optipng=args.optipng,
        opt_level=args.opt_level,
        extra_args=tuple(args.optipng_arg),
        strip=args.strip,
        timeout=args.timeout,
        dry_run=args.dry_run,
    )

    counters: dict[str, int] = {
        "OK": 0,
        "DRY-RUN": 0,
        "NOCHG": 0,
        "SAME": 0,
        "SKIP": 0,
        "ERROR": 0,
    }
    total_before = 0
    total_after = 0

    files = iter_png_files(roots)

    try:
        with Pool(processes=DEFAULT_WORKERS) as pool:
            for result in pool.imap_unordered(worker, files, chunksize=IMAP_CHUNKSIZE):
                if not args.quiet:
                    _emit_optipng_output(result)

                tag = _classify(result, args.dry_run)
                counters[tag] += 1

                # Only OK and DRY-RUN represent an actual / potential saving.
                if tag in ("OK", "DRY-RUN"):
                    total_before += result.original_size
                    total_after += result.new_size

                _print_status(result, tag)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130

    _print_summary(counters, total_before, total_after)

    return 1 if counters["ERROR"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
