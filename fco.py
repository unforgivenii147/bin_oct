#!/data/data/com.termux/files/home/.local/bin/python
"""Generate a font converter CLI that converts font files between TTF, OTF, WOFF, and WOFF2 formats.

The script should:
- Use argparse for CLI parsing with inputs (files/dirs, default cwd), --to (output format, default woff2), -r/--remove, -o/--output-dir, -f/--force, --dry-run, -v/--verbose.
- Use pathlib.Path for all path handling.
- Use loguru for logging.
- Use multiprocessing.Pool.apply_async with a fixed pool of 8 workers for parallel conversion.
- Use fontTools.ttLib.TTFont to load and save fonts, setting flavor for woff/woff2 and sfntVersion for ttf/otf, with warnings when outline type mismatches format convention.
- Detect formats by file extension, skip files already in target format, deduplicate discovered files.
- Recursively scan directories for supported font extensions (case-insensitive).
- Optionally remove originals after successful conversion (only if different path and non-empty output).
- Print per-file stats (sizes, ratio, time, warnings, removal) and a summary.
- Support --dry-run to list conversions without performing them.
- Exit with code 1 if any conversion fails, 0 otherwise; exit 130 on KeyboardInterrupt.
- Require brotli for woff2 output, exiting with an error if missing.
- Include full type annotations passing strict type checking.
"""

from __future__ import annotations

import argparse
import sys
import time
from multiprocessing import Pool
from pathlib import Path
from typing import Any, List

from dh import fsz
from loguru import logger

try:
    from fontTools.ttLib import TTFont
except ImportError:
    sys.stderr.write("fonttools is not installed.\n  pip install fonttools\n")
    sys.exit(1)

try:
    import brotli  # noqa: F401

    _HAS_BROTLI: bool = True
except ImportError:
    _HAS_BROTLI = False

SUPPORTED_FORMATS: set[str] = {"ttf", "otf", "woff", "woff2"}
SFNT_VERSIONS: dict[str, int | str] = {
    "ttf": 0x00010000,
    "otf": "OTTO",
}
FLAVORS: dict[str, str] = {
    "woff": "woff",
    "woff2": "woff2",
}
DEFAULT_OUTPUT_FORMAT: str = "woff2"
FIXED_WORKERS: int = 8


def detect_format(path: Path) -> str | None:
    """Return the lowercase font format from a path's extension, or None if unsupported."""
    ext = path.suffix.lower().lstrip(".")
    return ext if ext in SUPPORTED_FORMATS else None


def generate_output_path(
    input_path: Path,
    output_format: str,
    output_dir: Path | None = None,
) -> Path:
    """Build the output path for a converted font, optionally inside output_dir."""
    stem = input_path.stem
    if output_dir is not None:
        return output_dir / f"{stem}.{output_format}"
    return input_path.with_suffix(f".{output_format}")


def convert_font(
    input_path: Path,
    output_format: str,
    remove_original: bool,
    output_dir: Path | None,
    force: bool,
) -> dict[str, Any]:
    """Convert a single font file to the requested format and return a stats dict."""
    stats: dict[str, Any] = {
        "input": str(input_path),
        "output": None,
        "input_format": None,
        "output_format": output_format,
        "input_size": 0,
        "output_size": 0,
        "time": 0.0,
        "success": False,
        "error": None,
        "warning": None,
        "removed_original": False,
    }
    start = time.perf_counter()
    try:
        input_format = detect_format(input_path)
        if input_format is None:
            raise ValueError(f"unsupported extension '{input_path.suffix}'")
        stats["input_format"] = input_format
        if input_format == output_format:
            raise ValueError(f"already .{output_format}")
        output_path = generate_output_path(input_path, output_format, output_dir)
        stats["output"] = str(output_path)
        if output_path.exists() and not force:
            raise FileExistsError(f"output exists (use --force): {output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        input_size = input_path.stat().st_size
        stats["input_size"] = input_size
        font = TTFont(str(input_path), lazy=False)
        has_cff = "CFF " in font or "CFF2" in font
        has_glyf = "glyf" in font
        warning: str | None = None
        font.flavor = FLAVORS.get(output_format)
        if output_format in SFNT_VERSIONS:
            if output_format == "otf" and has_glyf and not has_cff:
                warning = (
                    "font has TrueType outlines; .otf conventionally uses CFF "
                    "— outlines were NOT converted"
                )
            elif output_format == "ttf" and has_cff and not has_glyf:
                warning = (
                    "font has CFF outlines; .ttf conventionally uses TrueType "
                    "— outlines were NOT converted"
                )
            font.sfntVersion = SFNT_VERSIONS[output_format]
        font.save(str(output_path))
        font.close()
        output_size = output_path.stat().st_size
        elapsed = time.perf_counter() - start
        stats["output_size"] = output_size
        stats["time"] = elapsed
        stats["success"] = True
        stats["warning"] = warning
        if (
            remove_original
            and input_path.resolve() != output_path.resolve()
            and output_path.exists()
            and output_path.stat().st_size > 0
        ):
            input_path.unlink()
            stats["removed_original"] = True
    except Exception as exc:
        stats["error"] = str(exc)
        stats["time"] = time.perf_counter() - start
    return stats


def find_font_files(paths: list[Path]) -> list[Path]:
    """Recursively discover supported font files from the given paths, deduplicated."""
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            if detect_format(path):
                files.append(path)
            else:
                logger.warning("skipping non-font file: {}", path)
        elif path.is_dir():
            for ext in SUPPORTED_FORMATS:
                files.extend(path.rglob(f"*.{ext}"))
                files.extend(path.rglob(f"*.{ext.upper()}"))
        else:
            logger.warning("path not found: {}", path)
    seen: set[Path] = set()
    unique: list[Path] = []
    for f in files:
        r = f.resolve()
        if r not in seen:
            seen.add(r)
            unique.append(f)
    return unique


def print_file_stats(stats: dict[str, Any]) -> None:
    """Log per-file conversion statistics."""
    name = Path(stats["input"]).name
    status = "✓" if stats["success"] else "✗"
    if stats["success"]:
        in_sz = stats["input_size"]
        out_sz = stats["output_size"]
        ratio = (out_sz / in_sz * 100) if in_sz else 0.0
        saved = (1 - out_sz / in_sz) * 100 if in_sz else 0.0
        print("  {} {}", status, name)
        print(
            "      {} → {}  ({:.1f}% of original, {:+.1f}% change)",
            fsz(in_sz),
            fsz(out_sz),
            ratio,
            saved,
        )
        print("      Time: {:.3f}s", stats["time"])
        if stats["warning"]:
            logger.warning("      ⚠  {}", stats["warning"])
        if stats["removed_original"]:
            print("      🗑  original removed")
    else:
        logger.error("  {} {} — ERROR: {}", status, name, stats["error"])


def print_summary(all_stats: list[dict[str, Any]]) -> None:
    """Log an aggregate summary of all conversions."""
    total = len(all_stats)
    ok = sum(1 for s in all_stats if s["success"])
    fail = total - ok
    print()
    print("=" * 40)
    print("Summary")
    print("-" * 40)
    print("  Files processed : {}", total)
    print("  Successful      : {}", ok)
    print("  Failed          : {}", fail)
    if ok:
        total_in = sum(s["input_size"] for s in all_stats if s["success"])
        total_out = sum(s["output_size"] for s in all_stats if s["success"])
        total_time = sum(s["time"] for s in all_stats if s["success"])
        print("  Input size      : {}", fsz(total_in))
        print("  Output size     : {}", fsz(total_out))
        if total_in:
            print(
                "  Ratio           : {:.1f}% of original",
                total_out / total_in * 100,
            )
        print("  Total time      : {:.3f}s", total_time)
        if total > 1:
            print("  Avg per file    : {:.3f}s", total_time / total)
    print("=" * 40)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Convert font files between TTF, OTF, WOFF, and WOFF2.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s                              Convert all fonts in cwd → woff2
  %(prog)s font.ttf --to woff            Single file → woff
  %(prog)s ./fonts/ --to ttf -r         Dir → ttf, remove originals
  %(prog)s a.ttf b.otf --to woff2        Two files
  %(prog)s ./fonts/ --to otf -o ./out/   Output to ./out/ directory
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
    return parser.parse_args()


def main() -> None:
    """Entry point: parse args, discover fonts, convert in parallel, print summary."""
    args = parse_args()

    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG" if args.verbose else "WARNING",
        format="<level>{level: <8}</level> | <level>{message}</level>",
    )

    if args.output_format == "woff2" and not _HAS_BROTLI:
        sys.stderr.write("WOFF2 output requires brotli.\n  pip install brotli\n")
        sys.exit(1)

    input_paths: list[Path] = args.inputs if args.inputs else [Path.cwd()]
    font_files = find_font_files(input_paths)
    if not font_files:
        print("No font files found.")
        sys.exit(0)

    to_convert: list[Path] = []
    already_target: list[Path] = []
    for f in font_files:
        if detect_format(f) == args.output_format:
            already_target.append(f)
        else:
            to_convert.append(f)

    if already_target:
        print(
            "Skipping {} file(s) already in .{} format",
            len(already_target),
            args.output_format,
        )

    if not to_convert:
        print("Nothing to convert.")
        sys.exit(0)

    print()
    print("Converting {} file(s) → .{}", len(to_convert), args.output_format)
    if args.remove:
        print("  (originals will be removed on success)")
    print()

    if args.dry_run:
        for f in to_convert:
            out = generate_output_path(f, args.output_format, args.output_dir)
            print("  {}  →  {}", f, out)
        sys.exit(0)

    all_stats: list[dict[str, Any]] = []

    if len(to_convert) == 1:
        all_stats.append(
            convert_font(
                to_convert[0],
                args.output_format,
                args.remove,
                args.output_dir,
                args.force,
            )
        )
        print_file_stats(all_stats[0])
    else:
        workers = min(FIXED_WORKERS, len(to_convert))
        pool = Pool(processes=workers)
        try:
            async_results = [
                pool.apply_async(
                    convert_font,
                    args=(
                        f,
                        args.output_format,
                        args.remove,
                        args.output_dir,
                        args.force,
                    ),
                )
                for f in to_convert
            ]
            try:
                for ar in async_results:
                    stats: dict[str, Any] = ar.get()
                    all_stats.append(stats)
                    print_file_stats(stats)
            except KeyboardInterrupt:
                print()
                print("Interrupted — terminating pool …")
                pool.terminate()
                pool.join()
                for ar in async_results:
                    if ar.ready():
                        try:
                            all_stats.append(ar.get(timeout=0))
                        except Exception:
                            pass
                print_summary(all_stats)
                sys.exit(130)
        finally:
            pool.close()
            pool.join()

    print_summary(all_stats)
    failed = sum(1 for s in all_stats if not s["success"])
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    raise SystemExit(main())
