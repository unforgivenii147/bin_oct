#!/data/data/com.termux/files/home/.local/bin/python
"""
font_toolkit.py — merged font conversion utilities.

Original scripts and their equivalents:
  font_convert.py       -> python font_toolkit.py convert --to <fmt> [paths...] [--rm]
  otf2ttf.py            -> python font_toolkit.py otf2ttf [paths...] [--workers N] [--keep-source]
  otf_to_ttf.py         -> python font_toolkit.py otf2ttf-fontforge [paths...] [--keep-source]
  tottf.py              -> python font_toolkit.py tottf [paths...] [--remove-source]
  woff22ttf.py          -> python font_toolkit.py woff22ttf [paths...] [--workers N] [--keep-source]

Third-party dependencies:
  fontTools   (pip install fonttools)   — required for convert, otf2ttf, woff22ttf
  fontforge   (system package)          — required for otf2ttf-fontforge and tottf

Usage examples:
  # Convert all fonts in current dir to woff2, remove originals
  python font_toolkit.py convert --to woff2 --rm

  # Convert specific OTF files to TTF with 8 workers, keep originals
  python font_toolkit.py otf2ttf font1.otf font2.otf --workers 8 --keep-source

  # Convert OTF to TTF using FontForge (keeps originals)
  python font_toolkit.py otf2ttf-fontforge ./fonts

  # Convert svg/woff/eot/otf/ttc to TTF using FontForge CLI, remove source
  python font_toolkit.py tottf --remove-source ./assets

  # Decompress WOFF2 to TTF, remove originals
  python font_toolkit.py woff22ttf ./webfonts
"""

from __future__ import annotations

import argparse
import multiprocessing
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Optional third-party imports
# ---------------------------------------------------------------------------
try:
    from fontTools.ttLib import TTFont
    from fontTools.ttLib import woff2
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    HAS_FONTTOOLS = True
except ImportError:
    HAS_FONTTOOLS = False

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def unique_path(path: Path) -> Path:
    """Return a path that does not exist by appending _1, _2, ... before suffix."""
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        new_path = parent / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1


def collect_files(
    paths: Sequence[str],
    extensions: Sequence[str],
) -> List[Path]:
    """
    Collect files from given paths (files or directories).
    If no paths given, scan the current working directory recursively.
    Extensions are matched case-insensitively and should include the dot (e.g. '.ttf').
    """
    ext_set = {ext.lower() for ext in extensions}
    result: List[Path] = []

    if not paths:
        paths = [str(Path.cwd())]

    for p_str in paths:
        p = Path(p_str)
        if p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and f.suffix.lower() in ext_set:
                    result.append(f)
        elif p.is_file():
            if p.suffix.lower() in ext_set:
                result.append(p)
            else:
                print(
                    f"Warning: {p} does not match extensions {extensions}",
                    file=sys.stderr,
                )
        else:
            print(f"Warning: path not found: {p}", file=sys.stderr)

    # Remove duplicates while preserving order
    seen = set()
    unique: List[Path] = []
    for f in result:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return unique


def run_parallel(
    func: Callable,
    items: List,
    workers: int,
    *args,
) -> List:
    """Run func(item, *args) for each item, using a multiprocessing pool if workers > 1."""
    if workers <= 1 or len(items) <= 1:
        return [func(item, *args) for item in items]
    with multiprocessing.Pool(processes=workers) as pool:
        return pool.starmap(func, [(item, *args) for item in items])


# ---------------------------------------------------------------------------
# Subcommand: convert (font_convert.py)
# ---------------------------------------------------------------------------


def _convert_worker(src: Path, target_ext: str, remove_source: bool) -> None:
    """Convert a single font file to target format."""
    if not HAS_FONTTOOLS:
        print(
            "Error: fontTools is required for 'convert'. Install with: pip install fonttools",
            file=sys.stderr,
        )
        return

    flavor_map = {
        "woff": "woff",
        "woff2": "woff2",
        "ttf": None,
    }
    flavor = flavor_map[target_ext]

    dst = src.with_suffix(f".{target_ext}")
    if dst.exists():
        dst = unique_path(dst)

    try:
        font = TTFont(src)
        font.flavor = flavor
        font.save(dst)
        print(f"{src.name} -> {dst.name}")
        if remove_source and src.exists():
            src.unlink()
    except Exception as exc:
        print(f"Error converting {src.name}: {exc}", file=sys.stderr)


def cmd_convert(args: argparse.Namespace) -> int:
    """Handler for 'convert' subcommand."""
    if not HAS_FONTTOOLS:
        print(
            "Error: fontTools is required. Install with: pip install fonttools",
            file=sys.stderr,
        )
        return 1

    extensions = [".ttf", ".otf", ".woff", ".woff2"]
    files = collect_files(args.paths, extensions)

    # Filter out files already in the target format
    target_suffix = f".{args.to}"
    files = [f for f in files if f.suffix.lower() != target_suffix]

    if not files:
        print(f"No font files to convert to {target_suffix}", file=sys.stderr)
        return 1

    run_parallel(_convert_worker, files, args.workers, args.to, args.rm)
    return 0


# ---------------------------------------------------------------------------
# Subcommand: otf2ttf (otf2ttf.py) — pure fontTools
# ---------------------------------------------------------------------------


def _otf2ttf_worker(src: Path, keep_source: bool) -> dict:
    """Convert OTF to TTF using fontTools. Returns status dict."""
    if not HAS_FONTTOOLS:
        return {"status": "failed", "error": "fontTools not installed", "otf": str(src)}

    dst = src.with_suffix(".ttf")
    status = {"otf": str(src), "ttf": str(dst), "status": "unknown"}

    if dst.exists():
        status["status"] = "skipped_exists"
        return status

    try:
        font = TTFont(src)
        if "glyf" in font:
            status["status"] = "skipped_already_ttf"
            return status

        cff_table = None
        if "CFF2" in font:
            cff_table = font["CFF2"]
        elif "CFF " in font:
            cff_table = font["CFF "]
        else:
            status["status"] = "failed_no_cff"
            return status

        glyph_order = font.getGlyphOrder()
        for glyph_name in glyph_order:
            if glyph_name in cff_table:
                pen = TTGlyphPen(None)
                cff_table[glyph_name].draw(pen)
                font["glyf"][glyph_name] = pen.glyph()

        font.flavor = None
        for tag in ["CFF ", "CFF2", "VORG"]:
            if tag in font:
                del font[tag]

        if "glyf" not in font:
            raise ValueError("Failed to create glyf table")

        font.sfVersion = "\x00\x01\x00\x00"
        font.reader = None
        font.save(dst)

        if not keep_source:
            src.unlink()

        status["status"] = "success"
    except Exception as exc:
        status["status"] = "failed"
        status["error"] = str(exc)
        if dst.exists():
            dst.unlink()

    return status


def cmd_otf2ttf(args: argparse.Namespace) -> int:
    """Handler for 'otf2ttf' subcommand."""
    if not HAS_FONTTOOLS:
        print(
            "Error: fontTools is required. Install with: pip install fonttools",
            file=sys.stderr,
        )
        return 1

    files = collect_files(args.paths, [".otf"])
    if not files:
        print("No OTF files found.", file=sys.stderr)
        return 1

    print(f"Found {len(files)} OTF file(s)")
    print(f"Using {args.workers} worker processes")

    results = run_parallel(_otf2ttf_worker, files, args.workers, args.keep_source)

    summary = {
        "total": len(results),
        "success": 0,
        "skipped_exists": 0,
        "skipped_already_ttf": 0,
        "failed": 0,
    }
    for res in results:
        st = res["status"]
        if st == "success":
            summary["success"] += 1
            print(
                f"  ✓ Converted: {res['ttf']} (original {'kept' if args.keep_source else 'removed'})"
            )
        elif st == "skipped_exists":
            summary["skipped_exists"] += 1
            print(f"  ⚠ Skipped: {res['ttf']} (already exists)")
        elif st == "skipped_already_ttf":
            summary["skipped_already_ttf"] += 1
            print(f"  ⚠ Skipped: {res['otf']} (already has TrueType outlines)")
        else:
            summary["failed"] += 1
            err = res.get("error", "Unknown error")
            print(f"  ✗ Failed: {res['otf']} — {err}")

    print("\n" + "=" * 40)
    print("Conversion Summary:")
    print(f"  Total OTF files found: {summary['total']}")
    print(f"  Successfully converted: {summary['success']}")
    print(f"  Skipped (TTF exists): {summary['skipped_exists']}")
    print(f"  Skipped (already TrueType): {summary['skipped_already_ttf']}")
    print(f"  Failed: {summary['failed']}")
    return 0 if summary["failed"] == 0 else 1


# ---------------------------------------------------------------------------
# Subcommand: otf2ttf-fontforge (otf_to_ttf.py)
# ---------------------------------------------------------------------------


def _otf2ttf_fontforge_worker(src: Path, keep_source: bool) -> Tuple[str, str]:
    """Convert OTF to TTF using FontForge Python bindings. Returns (status, message)."""
    try:
        import fontforge
    except ImportError:
        return ("error", "FontForge Python module not available")

    dst = src.with_suffix(".ttf")
    if dst.exists():
        return ("skipped", str(dst))

    try:
        font = fontforge.open(str(src))
        font.generate(str(dst), flags=("opentype",))
        font.close()
        if not keep_source:
            src.unlink()
        return ("success", str(dst))
    except Exception as exc:
        return ("error", str(exc))


def cmd_otf2ttf_fontforge(args: argparse.Namespace) -> int:
    """Handler for 'otf2ttf-fontforge' subcommand."""
    try:
        import fontforge  # noqa: F401
    except ImportError:
        print("This script must be run with FontForge's Python interpreter:")
        print("  fontforge-script font_toolkit.py otf2ttf-fontforge ...")
        return 1

    files = collect_files(args.paths, [".otf"])
    if not files:
        print("No OTF files found.", file=sys.stderr)
        return 1

    print(f"Found {len(files)} OTF file(s)\n")
    summary = {"success": 0, "skipped": 0, "error": 0}
    for src in files:
        print(f"Processing: {src}")
        status, msg = _otf2ttf_fontforge_worker(src, args.keep_source)
        if status == "success":
            print(
                f"  ✓ Converted: {msg} (original {'kept' if args.keep_source else 'removed'})"
            )
            summary["success"] += 1
        elif status == "skipped":
            print(f"  ⚠ Skipped: {msg} (already exists)")
            summary["skipped"] += 1
        else:
            print(f"  ✗ Failed: {msg}")
            summary["error"] += 1

    print(f"\n{'=' * 40}")
    print(
        f"Summary: {summary['success']} converted, {summary['skipped']} skipped, {summary['error']} failed"
    )
    return 0 if summary["error"] == 0 else 1


# ---------------------------------------------------------------------------
# Subcommand: tottf (tottf.py) — FontForge CLI
# ---------------------------------------------------------------------------


def _tottf_worker(src: Path, remove_source: bool) -> bool:
    """Convert a font file to TTF using FontForge CLI. Returns True on success."""
    dst = src.with_suffix(".ttf")
    cmd = [
        "fontforge",
        "-lang=ff",
        "-c",
        '"Open($1); Generate($2);"',
        str(src),
        str(dst),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            print(f"✓ {src.name}")
            if remove_source and src.exists():
                src.unlink()
            return True
        else:
            print(f"✘ {src.name}: {result.stderr.strip()}", file=sys.stderr)
            return False
    except Exception as exc:
        print(f"Error processing {src.name}: {exc}", file=sys.stderr)
        return False


def cmd_tottf(args: argparse.Namespace) -> int:
    """Handler for 'tottf' subcommand."""
    extensions = [".svg", ".woff", ".eot", ".otf", ".ttc"]
    files = collect_files(args.paths, extensions)
    if not files:
        print("No matching font files found.", file=sys.stderr)
        return 1

    success = 0
    for src in files:
        if src.suffix.lower() != ".ttf":
            if _tottf_worker(src, args.remove_source):
                success += 1

    print(f"\nConverted {success}/{len(files)} files.")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: woff22ttf (woff22ttf.py)
# ---------------------------------------------------------------------------


def _woff22ttf_worker(src: Path, keep_source: bool) -> bool:
    """Decompress WOFF2 to TTF. Returns True on success."""
    if not HAS_FONTTOOLS:
        print(
            "Error: fontTools is required. Install with: pip install fonttools",
            file=sys.stderr,
        )
        return False

    dst = src.with_suffix(".ttf")
    if dst.exists() and dst.stat().st_size:
        print(f"{src.name} already converted.")
        return True

    try:
        woff2.decompress(str(src), str(dst))
        print(f"{src.name} converted.")
        if not keep_source:
            src.unlink()
        return True
    except Exception as exc:
        print(f"Error converting {src.name}: {exc}", file=sys.stderr)
        return False


def cmd_woff22ttf(args: argparse.Namespace) -> int:
    """Handler for 'woff22ttf' subcommand."""
    if not HAS_FONTTOOLS:
        print(
            "Error: fontTools is required. Install with: pip install fonttools",
            file=sys.stderr,
        )
        return 1

    files = collect_files(args.paths, [".woff2"])
    if not files:
        print("No WOFF2 files found.", file=sys.stderr)
        return 1

    print(f"Found {len(files)} WOFF2 file(s)")
    run_parallel(_woff22ttf_worker, files, args.workers, args.keep_source)
    return 0


# ---------------------------------------------------------------------------
# CLI setup
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="font_toolkit.py",
        description="Merged font conversion toolkit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- convert ---
    p_convert = subparsers.add_parser(
        "convert",
        help="Convert TTF/OTF/WOFF/WOFF2 fonts to another container flavour.",
    )
    p_convert.add_argument(
        "paths", nargs="*", help="Font files or directories (default: scan cwd)"
    )
    p_convert.add_argument(
        "--to", required=True, choices=["ttf", "woff", "woff2"], help="Target format"
    )
    p_convert.add_argument(
        "-r",
        "--rm",
        action="store_true",
        help="Delete source file after successful conversion",
    )
    p_convert.add_argument(
        "-w",
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    p_convert.set_defaults(func=cmd_convert)

    # --- otf2ttf ---
    p_otf2ttf = subparsers.add_parser(
        "otf2ttf",
        help="Convert OTF to TTF using fontTools (pure Python).",
    )
    p_otf2ttf.add_argument(
        "paths", nargs="*", help="OTF files or directories (default: scan cwd)"
    )
    p_otf2ttf.add_argument(
        "-w",
        "--workers",
        type=int,
        default=6,
        help="Number of parallel workers (default: 6)",
    )
    p_otf2ttf.add_argument(
        "-k",
        "--keep-source",
        action="store_true",
        help="Keep original OTF files (default: remove)",
    )
    p_otf2ttf.set_defaults(func=cmd_otf2ttf)

    # --- otf2ttf-fontforge ---
    p_otf2ttf_ff = subparsers.add_parser(
        "otf2ttf-fontforge",
        help="Convert OTF to TTF using FontForge Python bindings.",
    )
    p_otf2ttf_ff.add_argument(
        "paths", nargs="*", help="OTF files or directories (default: scan cwd)"
    )
    p_otf2ttf_ff.add_argument(
        "-k",
        "--keep-source",
        action="store_true",
        help="Keep original OTF files (default: remove)",
    )
    p_otf2ttf_ff.set_defaults(func=cmd_otf2ttf_fontforge)

    # --- tottf ---
    p_tottf = subparsers.add_parser(
        "tottf",
        help="Convert SVG/WOFF/EOT/OTF/TTC to TTF using FontForge CLI.",
    )
    p_tottf.add_argument(
        "paths", nargs="*", help="Font files or directories (default: scan cwd)"
    )
    p_tottf.add_argument(
        "-r",
        "--remove-source",
        action="store_true",
        help="Delete source file after successful conversion",
    )
    p_tottf.set_defaults(func=cmd_tottf)

    # --- woff22ttf ---
    p_woff22 = subparsers.add_parser(
        "woff22ttf",
        help="Decompress WOFF2 to TTF using fontTools.",
    )
    p_woff22.add_argument(
        "paths", nargs="*", help="WOFF2 files or directories (default: scan cwd)"
    )
    p_woff22.add_argument(
        "-w",
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    p_woff22.add_argument(
        "-k",
        "--keep-source",
        action="store_true",
        help="Keep original WOFF2 files (default: remove)",
    )
    p_woff22.set_defaults(func=cmd_woff22ttf)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nConversion interrupted by user.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
