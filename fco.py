#!/data/data/com.termux/files/home/.local/bin/python
"""
merged_font_converter.py

Merged refactor of fco.py and fontconverter.py.

Features kept:
- TTF / OTF / WOFF / WOFF2 conversion via fontTools.
- Recursive directory input.
- Output directory, force overwrite, dry-run, verbose logging.
- Parallel conversion with multiprocessing.
- Optional original removal after successful conversion.
- Safe default: refuses TTF<->OTF outline mismatches unless
  --allow-outline-mismatch is given.

Requires:
    pip install fonttools loguru brotli

Also imports `fsz` from a local `dh` module, same as the original scripts.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path
from typing import List, Optional, Sequence

from dh import fsz
from loguru import logger

try:
    from fontTools.ttLib import TTFont
except ImportError:
    sys.stderr.write("fonttools is not installed.\n  pip install fonttools\n")
    sys.exit(1)

try:
    import brotli  # noqa: F401

    HAS_BROTLI = True
except ImportError:
    HAS_BROTLI = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_FORMATS = frozenset({"ttf", "otf", "woff", "woff2"})

SFNT_VERSIONS = {
    "ttf": 0x00010000,
    "otf": "OTTO",
}

FLAVORS = {
    "woff": "woff",
    "woff2": "woff2",
}

DEFAULT_OUTPUT_FORMAT = "woff2"
DEFAULT_WORKERS = 8

CFF_TABLES = frozenset({"CFF ", "CFF2"})
TRUETYPE_TABLE = "glyf"


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class ConversionResult:
    """Result of one font conversion attempt."""

    input: Path
    output_format: str
    output: Optional[Path] = None
    input_format: Optional[str] = None
    input_size: int = 0
    output_size: int = 0
    time: float = 0.0
    success: bool = False
    skipped: bool = False
    skipped_reason: Optional[str] = None
    error: Optional[str] = None
    warning: Optional[str] = None
    removed_original: bool = False

    @property
    def failed(self) -> bool:
        """True only for real failures, not intentional skips."""
        return not self.success and not self.skipped


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def detect_format(path: Path) -> Optional[str]:
    """Return normalized font extension if supported, else None."""
    ext = path.suffix.lower().lstrip(".")
    return ext if ext in SUPPORTED_FORMATS else None


def generate_output_path(
    input_path: Path,
    output_format: str,
    output_dir: Optional[Path] = None,
) -> Path:
    """Build output path, either alongside input or inside output_dir."""
    if output_dir is not None:
        return output_dir / f"{input_path.stem}.{output_format}"
    return input_path.with_suffix(f".{output_format}")


def _outline_kind(font: TTFont) -> str:
    """Return 'cff', 'truetype', or 'unknown' based on table tags."""
    tags = set(font.keys())
    if tags & CFF_TABLES:
        return "cff"
    if TRUETYPE_TABLE in tags:
        return "truetype"
    return "unknown"


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


def convert_font(
    input_path: Path,
    output_format: str,
    remove_original: bool,
    output_dir: Optional[Path],
    force: bool,
    allow_outline_mismatch: bool,
) -> ConversionResult:
    """
    Convert one font file.

    This function is top-level so it can be used with multiprocessing.Pool.
    """
    start = time.perf_counter()
    result = ConversionResult(input=input_path, output_format=output_format)
    output_existed_before = False

    try:
        input_format = detect_format(input_path)
        if input_format is None:
            raise ValueError(f"unsupported extension '{input_path.suffix}'")

        result.input_format = input_format
        result.input_size = input_path.stat().st_size

        # Already target format: skip.
        if input_format == output_format:
            result.skipped = True
            result.skipped_reason = f"already .{output_format}"
            return result

        output_path = generate_output_path(input_path, output_format, output_dir)
        result.output = output_path
        output_existed_before = output_path.exists()

        if output_existed_before and not force:
            raise FileExistsError(f"output exists (use --force): {output_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # lazy=True avoids loading unnecessary data; recalc flags preserve original.
        font = TTFont(
            str(input_path),
            lazy=True,
            recalcBBoxes=False,
            recalcTimestamp=False,
        )

        try:
            kind = _outline_kind(font)
            warning: Optional[str] = None

            # WOFF / WOFF2 are wrappers: set flavor only.
            if output_format in FLAVORS:
                font.flavor = FLAVORS[output_format]

            # TTF / OTF are sfnt containers: set flavor None and sfntVersion.
            else:
                font.flavor = None

                if output_format == "otf":
                    if kind == "cff":
                        pass
                    elif kind == "truetype":
                        if not allow_outline_mismatch:
                            result.skipped = True
                            result.skipped_reason = (
                                "source has TrueType (glyf) outlines; .otf "
                                "conventionally uses CFF. Use "
                                "--allow-outline-mismatch to write a "
                                "non-standard .otf anyway."
                            )
                            return result

                        warning = (
                            "font has TrueType outlines; .otf conventionally "
                            "uses CFF — outlines were NOT converted"
                        )
                    else:
                        if not allow_outline_mismatch:
                            result.skipped = True
                            result.skipped_reason = (
                                "no recognizable CFF outlines for .otf"
                            )
                            return result

                        warning = "no recognizable CFF outlines; .otf may be invalid"

                    font.sfntVersion = SFNT_VERSIONS["otf"]

                elif output_format == "ttf":
                    if kind == "truetype":
                        pass
                    elif kind == "cff":
                        if not allow_outline_mismatch:
                            result.skipped = True
                            result.skipped_reason = (
                                "source has CFF outlines; .ttf conventionally "
                                "uses TrueType outlines. Use "
                                "--allow-outline-mismatch to write a "
                                "non-standard .ttf anyway."
                            )
                            return result

                        warning = (
                            "font has CFF outlines; .ttf conventionally uses "
                            "TrueType — outlines were NOT converted"
                        )
                    else:
                        if not allow_outline_mismatch:
                            result.skipped = True
                            result.skipped_reason = (
                                "no recognizable TrueType outlines for .ttf"
                            )
                            return result

                        warning = (
                            "no recognizable TrueType outlines; .ttf may be invalid"
                        )

                    font.sfntVersion = SFNT_VERSIONS["ttf"]

                else:
                    raise ValueError(f"unsupported output format: {output_format}")

            font.save(str(output_path))

            result.output_size = output_path.stat().st_size
            result.success = True
            result.warning = warning

            # Remove original only after a successful save and non-empty output.
            if (
                remove_original
                and input_path.resolve() != output_path.resolve()
                and output_path.exists()
                and output_path.stat().st_size > 0
            ):
                try:
                    input_path.unlink()
                    result.removed_original = True
                except OSError as exc:
                    extra = f"conversion succeeded but could not remove original: {exc}"
                    result.warning = (
                        f"{result.warning}; {extra}" if result.warning else extra
                    )

        finally:
            with contextlib.suppress(Exception):
                font.close()

    except Exception as exc:
        result.error = str(exc)

        # Remove a partially-written new output, but never delete a pre-existing file.
        if (
            result.output is not None
            and not output_existed_before
            and result.output.exists()
            and not result.success
        ):
            with contextlib.suppress(OSError):
                result.output.unlink()

    finally:
        result.time = time.perf_counter() - start

    return result


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def find_font_files(paths: Sequence[Path]) -> List[Path]:
    """Find supported font files recursively, with case-insensitive suffixes."""
    files: List[Path] = []

    for path in paths:
        if path.is_file():
            if detect_format(path):
                files.append(path)
            else:
                logger.warning("skipping non-font file: {}", path)

        elif path.is_dir():
            for candidate in path.rglob("*"):
                if candidate.is_file() and detect_format(candidate):
                    files.append(candidate)

        else:
            logger.warning("path not found: {}", path)

    # Deduplicate by resolved path while preserving order.
    seen = set()
    unique: List[Path] = []
    for f in files:
        resolved = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(f)

    return unique


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_file_stats(result: ConversionResult) -> None:
    """Print one file's result."""
    name = result.input.name

    if result.success:
        ratio = (
            result.output_size / result.input_size * 100 if result.input_size else 0.0
        )
        saved = (
            (1 - result.output_size / result.input_size) * 100
            if result.input_size
            else 0.0
        )

        print(f"  ✓ {name}")
        print(
            f"      {fsz(result.input_size)} → {fsz(result.output_size)}  "
            f"({ratio:.1f}% of original, {saved:+.1f}% change)"
        )
        print(f"      Time: {result.time:.3f}s")

        if result.warning:
            logger.warning("      ⚠  {}", result.warning)

        if result.removed_original:
            print("      🗑  original removed")

    elif result.skipped:
        print(f"  ↷ {name} — SKIPPED: {result.skipped_reason}")

    else:
        print(f"  ✗ {name} — ERROR: {result.error}", file=sys.stderr)


def print_summary(results: Sequence[ConversionResult]) -> None:
    """Print overall summary."""
    total = len(results)
    ok = sum(1 for r in results if r.success)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if r.failed)

    print()
    print("=" * 40)
    print("Summary")
    print("-" * 40)
    print(f"  Files processed : {total}")
    print(f"  Successful      : {ok}")
    print(f"  Skipped         : {skipped}")
    print(f"  Failed          : {failed}")

    if ok:
        total_in = sum(r.input_size for r in results if r.success)
        total_out = sum(r.output_size for r in results if r.success)
        total_time = sum(r.time for r in results if r.success)

        print(f"  Input size      : {fsz(total_in)}")
        print(f"  Output size     : {fsz(total_out)}")

        if total_in:
            print(f"  Ratio           : {total_out / total_in * 100:.1f}% of original")

        print(f"  Total time      : {total_time:.3f}s")

        if total > 1:
            print(f"  Avg per file    : {total_time / total:.3f}s")

    print("=" * 40)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fontconverter.py",
        description="Convert font files between TTF, OTF, WOFF, and WOFF2.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s                              Convert all fonts in cwd → woff2
  %(prog)s font.ttf --to woff            Single file → woff
  %(prog)s ./fonts/ --to ttf -r          Dir → ttf, remove originals
  %(prog)s a.ttf b.otf --to woff2        Two files
  %(prog)s ./fonts/ --to otf -o ./out/   Output to ./out/ directory
  %(prog)s ./fonts/ --to otf --allow-outline-mismatch
                                        Allow non-standard TTF↔OTF mismatch
""",
    )

    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="Input font files or directories (default: current directory, recursive)",
    )

    parser.add_argument(
        "--to",
        "-t",
        dest="output_format",
        choices=sorted(SUPPORTED_FORMATS),
        default=DEFAULT_OUTPUT_FORMAT,
        help=f"Output format (default: {DEFAULT_OUTPUT_FORMAT})",
    )

    parser.add_argument(
        "-r",
        "--remove",
        action="store_true",
        help="Remove original file after successful conversion",
    )

    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: alongside each input)",
    )

    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite existing output files",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files that would be converted without converting",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )

    parser.add_argument(
        "--allow-outline-mismatch",
        action="store_true",
        help=(
            "Allow TTF↔OTF conversions even when outlines do not match the "
            "target convention. This writes a non-standard font and only "
            "changes the sfnt version; outlines are NOT converted."
        ),
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Number of worker processes (default: {DEFAULT_WORKERS})",
    )

    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG" if args.verbose else "WARNING",
        format="<level>{level: <8}</level> | <level>{message}</level>",
    )

    if args.output_format == "woff2" and not HAS_BROTLI:
        sys.stderr.write("WOFF2 output requires brotli.\n  pip install brotli\n")
        return 1

    input_paths = list(args.inputs) if args.inputs else [Path.cwd()]
    font_files = find_font_files(input_paths)

    if not font_files:
        print("No font files found.")
        return 0

    to_convert: List[Path] = []
    already_target: List[Path] = []

    for f in font_files:
        if detect_format(f) == args.output_format:
            already_target.append(f)
        else:
            to_convert.append(f)

    if already_target:
        print(
            f"Skipping {len(already_target)} file(s) already in "
            f".{args.output_format} format"
        )

    if not to_convert:
        print("Nothing to convert.")
        return 0

    print()
    print(f"Converting {len(to_convert)} file(s) → .{args.output_format}")

    if args.remove:
        print("  (originals will be removed on success)")

    if args.allow_outline_mismatch:
        print("  (outline mismatches allowed; output may be non-standard)")

    print()

    if args.dry_run:
        for f in to_convert:
            out = generate_output_path(f, args.output_format, args.output_dir)
            print(f"  {f}  →  {out}")
        return 0

    worker_args = [
        (
            f,
            args.output_format,
            args.remove,
            args.output_dir,
            args.force,
            args.allow_outline_mismatch,
        )
        for f in to_convert
    ]

    all_results: List[ConversionResult] = []

    # Single file: run in-process to keep output simple and avoid pool overhead.
    if len(worker_args) == 1:
        result = convert_font(*worker_args[0])
        all_results.append(result)
        print_file_stats(result)

    # Multiple files: use a process pool.
    else:
        workers = max(1, min(args.workers, len(worker_args)))
        pool = Pool(processes=workers)

        try:
            async_results = [
                pool.apply_async(convert_font, args=wa) for wa in worker_args
            ]

            try:
                for ar in async_results:
                    result = ar.get()
                    all_results.append(result)
                    print_file_stats(result)

            except KeyboardInterrupt:
                print()
                print("Interrupted — terminating pool …")
                pool.terminate()
                pool.join()

                # Collect any already-finished results before exiting.
                for ar in async_results:
                    if ar.ready():
                        try:
                            all_results.append(ar.get(timeout=0))
                        except Exception:
                            pass

                print_summary(all_results)
                return 130

        finally:
            with contextlib.suppress(Exception):
                pool.close()
            with contextlib.suppress(Exception):
                pool.join()

    print_summary(all_results)

    failed = sum(1 for r in all_results if r.failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
