#!/data/data/com.termux/files/home/.local/bin/python
"""Minify ``.js`` / ``.mjs`` / ``.cjs`` files in place using ``terser``.

The script discovers JavaScript files (case-insensitively, across ``.js``,
``.mjs`` and ``.cjs`` extensions) under the paths supplied on the command
line, runs ``terser`` on each of them through a bounded
``multiprocessing.Pool``, validates the result, and — only when the result is
non-empty, not byte-identical, and strictly smaller by at least
``MIN_SAVINGS_BYTES`` — atomically replaces the original. ``--mangle`` and
``--compress`` are on by default and can be turned off with ``--no-mangle``
/ ``--no-compress``.

Design highlights
-----------------
* Discovery uses the Rust ``fastwalk`` extension (``walk_files``). Because
  that helper exposes no pruning hooks, every filter (``SKIP_DIRS``,
  case-insensitive ``JS_SUFFIXES``, symlinks, deduplication) is applied in
  Python on the returned list.
* ``terser`` accepts ``-o OUTPUT`` and writes there directly, so the worker
  allocates a sibling temp file, points terser at it, validates the result,
  and only then swaps it in via ``os.replace``. The original mode bits are
  preserved.
* **On any terser error the original file is never touched.** The temp file
  is unlinked in the worker's ``finally`` block and the report carries an
  ``ERROR`` tag with a short message.
* **Trivial savings are ignored.** If terser's output is only
  ``MIN_SAVINGS_BYTES - 1`` bytes smaller (i.e. saves 0 or 1 byte), the
  write is skipped and the file is reported as ``NOCHG`` — the inode churn,
  mtime bump, and risk of a crash mid-replace are not worth a single byte.
* **Paths are shown relative to the current working directory** wherever
  possible, keeping output compact and making logs from different machines
  comparable. Absolute paths are used only when relpath fails.
* Every file is processed in a worker process; the parent prints each
  worker's captured ``terser`` stdout/stderr verbatim, so lines never
  interleave across workers.
* Failures never propagate out of a worker: they are reported through the
  ``error`` field of :class:`ProcessResult`.
* A non-zero exit code from ``main`` signals that at least one file errored.

Well-formedness
---------------
JavaScript has no magic number, so unlike the SVG / PNG / JPEG siblings there
is no cheap signature check. Instead we rely on terser itself: it parses the
input, transforms the AST, and only then serialises the output. A terser
exit code of 0 therefore implies both that the input parsed and that the
output was written. The only additional check we apply is that the output is
non-empty.

External requirements: the ``fastwalk`` extension module and the ``terser``
CLI (or a compatible path supplied via ``--terser``).
"""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
import tempfile
from functools import partial
from multiprocessing import Pool
from pathlib import Path
from typing import Final, Iterator, NamedTuple, Sequence

from fastwalk import walk_files
from dh import cprint, rrs
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

#: Accepted JavaScript suffixes, all lower-case. Matching is done on
#: ``path.suffix.lower()`` so ``.js``, ``.JS``, ``.Mjs`` and every other
#: casing qualifies. ``.mjs`` is the canonical ES-module extension and
#: ``.cjs`` the CommonJS one; terser handles both.
#: Extend this set to recognise further extensions (e.g. ``.jsx``, though
#: JSX needs a custom parser plugin and so is deliberately not enabled here).
JS_SUFFIXES: Final[frozenset[str]] = frozenset({".js", ".mjs", ".cjs"})

#: Slice size used when iterating the list returned by ``walk_files``.
WALK_CHUNK: Final[int] = 512

#: Fixed size of the worker pool (no CLI flag by design).
DEFAULT_WORKERS: Final[int] = 8

#: ``imap_unordered`` chunksize; small enough to keep the parent responsive.
IMAP_CHUNKSIZE: Final[int] = 4

#: Default per-file terser timeout, in seconds.
DEFAULT_TIMEOUT: Final[float] = 300.0

#: Chunk size used for the streaming byte-identity comparison.
COMPARE_CHUNK: Final[int] = 1 << 16

#: terser's exit code for a successful run. Any non-zero is treated as an
#: error.
TERSER_SUCCESS: Final[int] = 0

#: Minimum byte saving required before we actually rewrite the file. A saving
#: of 0 bytes (same-size-different-bytes) or 1 byte is treated as "no change":
#: the inode churn, mtime bump, and crash-window risk dwarf the benefit.
MIN_SAVINGS_BYTES: Final[int] = 2


# --------------------------------------------------------------------------- #
# Result record
# --------------------------------------------------------------------------- #


class ProcessResult(NamedTuple):
    """Outcome of processing a single JavaScript file.

    Attributes
    ----------
    path:
        The path as the parent discovered it (may be relative).
    original_size:
        Size of the original file in bytes, or ``0`` when it could not be
        determined.
    new_size:
        Size of terser's output in bytes, or ``0`` when no output was
        produced.
    stdout:
        Decoded stdout of the terser subprocess (UTF-8, ``errors="replace"``).
    stderr:
        Decoded stderr of the terser subprocess (UTF-8, ``errors="replace"``).
    skipped:
        ``True`` when the original was preserved because terser's output was
        *larger* than the input.
    no_change:
        ``True`` when the output was either byte-identical, or strictly
        smaller by fewer than ``MIN_SAVINGS_BYTES`` bytes. No write was
        performed and no mtime was bumped.
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


def display_path(path: Path) -> str:
    """Return *path* relative to the current working directory when possible.

    Keeping report lines relative keeps them compact and machine-independent.
    Falls back to the path as given if ``relpath`` cannot produce something
    sensible (e.g. on Windows when crossing drive letters).
    """
    try:
        return os.path.relpath(path, Path.cwd())
    except (OSError, ValueError):
        return str(path)


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
    """Yield JavaScript files under a single directory *root*.

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
            if path.suffix.lower() not in JS_SUFFIXES:
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


def iter_js_files(roots: Sequence[Path]) -> Iterator[Path]:
    """Yield deduplicated JavaScript files discovered under *roots*.

    Explicit files are accepted (subject to the JS-suffix filter and the
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
                # Never process a symlinked file: terser would read the
                # target but os.replace would then clobber the link itself.
                if raw_root.is_symlink():
                    print(
                        f"warning: skipping symlink: {raw_root}",
                        file=sys.stderr,
                    )
                    continue
                if raw_root.suffix.lower() in JS_SUFFIXES and _dedupe(raw_root, seen):
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


def _run_terser(
    cmd: Sequence[str], timeout: float
) -> tuple[subprocess.CompletedProcess[bytes] | None, str | None]:
    """Run *cmd* and return ``(completed, error)``.

    Exactly one of ``completed`` / ``error`` is non-``None``. All expected
    failure modes — timeout, missing executable, generic ``OSError`` — are
    translated into a short human-readable string so the caller never has to
    catch anything.
    """
    try:
        completed = subprocess.run(
            list(cmd),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, f"terser timed out after {timeout:g}s"
    except FileNotFoundError:
        return None, f"terser executable not found: {cmd[0]!r}"
    except OSError as exc:
        return None, f"failed to run terser: {exc}"
    return completed, None


def _build_terser_cmd(
    terser: str,
    target: Path,
    tmp_path: Path,
    *,
    mangle: bool,
    compress: bool,
    toplevel: bool,
    module: bool,
    ecma: int | None,
    extra_args: Sequence[str],
) -> list[str]:
    """Assemble the terser command line for one input / output pair.

    Options are emitted *before* the positional input so a path beginning
    with ``-`` cannot be misparsed as a flag; terser accepts ``-o OUTPUT``
    and writes there directly.
    """
    cmd: list[str] = [terser]
    if mangle:
        cmd.append("--mangle")
    if compress:
        cmd.append("--compress")
    # ``--toplevel`` only changes mangle/compress behaviour; emit it only
    # when either pass is enabled, otherwise it is a no-op that would just
    # confuse the resulting command line.
    if toplevel and (mangle or compress):
        cmd.append("--toplevel")
    if module:
        cmd.append("--module")
    if ecma is not None:
        cmd += ["--ecma", str(ecma)]
    cmd.extend(extra_args)
    cmd += ["-o", str(tmp_path), str(target)]
    return cmd


def process_file(
    path: Path,
    *,
    terser: str,
    mangle: bool,
    compress: bool,
    toplevel: bool,
    module: bool,
    ecma: int | None,
    extra_args: Sequence[str],
    timeout: float,
    dry_run: bool,
) -> ProcessResult:
    """Run terser on a single JS file and (optionally) replace it atomically.

    terser accepts ``-o OUTPUT`` and writes the minified result there
    directly, so we point it at a sibling temp file and only swap that file
    in once every validation gate has passed. On any error the original is
    left untouched: the temp file is unlinked in the ``finally`` block and
    the failure is reported through ``error``.

    This function never raises: every failure — a missing executable, a
    timeout, an empty result, a failed ``os.replace`` — is turned into an
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
        # ``app.MJS`` produces ``app.<rand>.MJS.tmp`` — cosmetic, but it
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

        # --- Build and run the terser command. ----------------------------
        cmd = _build_terser_cmd(
            terser,
            target,
            tmp_path,
            mangle=mangle,
            compress=compress,
            toplevel=toplevel,
            module=module,
            ecma=ecma,
            extra_args=extra_args,
        )
        completed, run_error = _run_terser(cmd, timeout)
        if completed is None:
            # Original untouched; tmp cleaned up in ``finally``.
            return ProcessResult(
                path, original_size, 0, "", "", False, False, run_error
            )

        stdout = completed.stdout.decode("utf-8", errors="replace")
        stderr = completed.stderr.decode("utf-8", errors="replace")

        if completed.returncode != TERSER_SUCCESS:
            # Original untouched; report the error and skip the write.
            return ProcessResult(
                path,
                original_size,
                0,
                stdout,
                stderr,
                False,
                False,
                f"terser exited with status {completed.returncode}",
            )

        # --- Validate terser's output. ------------------------------------
        # A successful terser run implies the input parsed and the AST was
        # serialised; the only cheap check left is that something was
        # actually written.
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
                f"terser produced no output: {exc}",
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
                "terser produced an empty file",
            )

        # --- Byte-identity short-circuit (runs before the size compare). --
        # When terser's transforms happen to leave the source unchanged —
        # or when the input was already minified — this is the normal
        # "nothing to do" path.
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

        # --- Trivial savings: treat as no change and skip the write. ------
        # Saves of 0 (same size, different bytes) or 1 byte are not worth a
        # new inode, a new mtime, and a crash window in the middle of
        # ``os.replace``.
        if original_size - new_size < MIN_SAVINGS_BYTES:
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

        # --- Strictly smaller by MIN_SAVINGS_BYTES or more: write. --------
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
    """Map a :class:`ProcessResult` onto one of the reporting tags.

    Tags
    ----
    ``ERROR``   : terser failed, timed out, or validation rejected its output.
    ``NOCHG``   : byte-identical, or savings below ``MIN_SAVINGS_BYTES``.
    ``SKIP``    : output was larger than the input.
    ``DRY-RUN`` : a write *would* happen, but ``--dry-run`` is set.
    ``OK``      : the original was replaced with a strictly smaller file.
    """
    if result.error is not None:
        return "ERROR"
    if result.no_change:
        return "NOCHG"
    if result.skipped:
        return "SKIP"
    if dry_run:
        return "DRY-RUN"
    return "OK"


def _emit_terser_output(result: ProcessResult) -> None:
    """Write the worker-captured terser streams to our own streams."""
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
    """Print a single, human-readable status line for *result*.

    The path is rendered relative to the current working directory so log
    lines stay compact and portable across machines.
    """
    shown = display_path(result.path)
    orig = result.original_size
    new = result.new_size

    if tag == "OK":
        saved = orig - new
        pct = (saved / orig * 100.0) if orig else 0.0
        print(
            f"[OK]      {shown}  "
            f"{format_bytes(orig)} -> {format_bytes(new)}  "
            f"(-{format_bytes(saved)}, -{pct:.1f}%)"
        )
    elif tag == "DRY-RUN":
        saved = orig - new
        pct = (saved / orig * 100.0) if orig else 0.0
        print(
            f"[DRY-RUN] {shown}  "
            f"{format_bytes(orig)} -> {format_bytes(new)}  "
            f"(would save {format_bytes(saved)}, {pct:.1f}%)"
        )
    elif tag == "NOCHG":
        # ``new_size`` is presented as ``original_size`` for this tag, so
        # there is nothing interesting to show beyond the size.
        print(f"[NOCHG]   {shown}  {format_bytes(orig)}  (no meaningful change)")
    elif tag == "SKIP":
        growth = new - orig
        print(
            f"[SKIP]    {shown}  "
            f"{format_bytes(orig)} -> {format_bytes(new)}  "
            f"(larger by {format_bytes(growth)})"
        )
    else:  # ERROR
        print(f"[ERROR]   {shown}  {result.error}", file=sys.stderr)


def _print_summary(
    counters: dict[str, int], total_before: int, total_after: int
) -> None:
    """Print the final aggregate report."""
    total = sum(counters.values())

    print()
    print("-" * 66)
    print("Summary")
    print("-" * 66)
    print(f"  Processed : {total}")
    print(f"  Changed   : {counters['OK']}")
    if counters["DRY-RUN"]:
        print(f"  Dry-run   : {counters['DRY-RUN']}")
    print(f"  Unchanged : {counters['NOCHG']}")
    print(f"  Skipped   : {counters['SKIP']}")
    if counters["SKIP"]:
        print(f"      (output was larger than input)")
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
        prog="terser-optimize",
        description=(
            "Minify .js / .mjs / .cjs files in place using terser. "
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
        help="Do not print terser's own stdout/stderr; only summary lines.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run and validate, but do not modify any files.",
    )
    # ``BooleanOptionalAction`` gives us both ``--mangle`` and ``--no-mangle``
    # (likewise for ``--compress``) from a single declaration.
    parser.add_argument(
        "--mangle",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Pass --mangle to terser (default: on). Use --no-mangle to skip.",
    )
    parser.add_argument(
        "--compress",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=("Pass --compress to terser (default: on). Use --no-compress to skip."),
    )
    parser.add_argument(
        "--toplevel",
        action="store_true",
        help=(
            "Pass --toplevel to terser (mangle/compress top-level names). "
            "Requires --mangle or --compress to have any effect."
        ),
    )
    parser.add_argument(
        "--module",
        action="store_true",
        help="Pass --module to terser (treat input as an ES module).",
    )
    parser.add_argument(
        "--ecma",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Pass --ecma N to terser (target ECMAScript version, e.g. 5, "
            "2015, 2020). Omitted by default so terser picks its own."
        ),
    )
    parser.add_argument(
        "--terser",
        default="terser",
        metavar="PATH",
        help="Path to the terser executable (default: search PATH).",
    )
    parser.add_argument(
        "--terser-arg",
        action="append",
        default=[],
        metavar="ARG",
        help="Extra argument to pass to terser; may be repeated.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help=f"Per-file terser timeout (default: {DEFAULT_TIMEOUT:g}s).",
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
        terser=args.terser,
        mangle=args.mangle,
        compress=args.compress,
        toplevel=args.toplevel,
        module=args.module,
        ecma=args.ecma,
        extra_args=tuple(args.terser_arg),
        timeout=args.timeout,
        dry_run=args.dry_run,
    )

    counters: dict[str, int] = {
        "OK": 0,
        "DRY-RUN": 0,
        "NOCHG": 0,
        "SKIP": 0,
        "ERROR": 0,
    }
    total_before = 0
    total_after = 0

    files = iter_js_files(roots)

    try:
        with Pool(processes=DEFAULT_WORKERS) as pool:
            for result in pool.imap_unordered(worker, files, chunksize=IMAP_CHUNKSIZE):
                if not args.quiet:
                    _emit_terser_output(result)

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
