#!/data/data/com.termux/files/home/.local/bin/python
"""Convert TTF/OTF/WOFF/WOFF2 font files using fontTools.

Prompt: Write a Python CLI script that recursively finds TTF, OTF, WOFF, and WOFF2
font files from given paths (or the current directory), converts each to a target
format using fontTools (woff/woff2 via flavor, ttf/otf only when outline tables
already match), optionally deletes the original after success, runs conversions in
a multiprocessing.Pool of 8 workers, logs with loguru, uses pathlib for all path
handling, and prints a final report table with sizes, ratios, times, and totals.
"""

from __future__ import annotations

import argparse
import contextlib
import time
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path
from typing import Final

from dh import fsz
from fontTools.ttLib import TTFont, TTLibError
from loguru import logger

SUPPORTED_EXTS: Final[frozenset[str]] = frozenset({".ttf", ".otf", ".woff", ".woff2"})
VALID_TARGETS: Final[frozenset[str]] = frozenset({"ttf", "otf", "woff", "woff2"})
CFF_TABLES: Final[frozenset[str]] = frozenset({"CFF ", "CFF2"})
TRUETYPE_TABLE: Final[str] = "glyf"
POOL_SIZE: Final[int] = 8


@dataclass
class ConvResult:
    """Result of converting a single font file."""

    src: Path
    dst: Path | None = None
    ok: bool = False
    skipped_reason: str | None = None
    error: str | None = None
    src_size: int = 0
    dst_size: int = 0
    seconds: float = 0.0
    removed_src: bool = False


def iter_font_files(paths: list[Path]) -> list[Path]:
    """Return a sorted list of font files found in the given files/directories."""
    found: set[Path] = set()
    for p in paths:
        if p.is_dir():
            for ext in SUPPORTED_EXTS:
                found.update(p.rglob(f"*{ext}"))
        elif p.is_file():
            if p.suffix.lower() in SUPPORTED_EXTS:
                found.add(p)
            else:
                logger.warning(f"ignoring non-font file: {p}")
    return sorted(found)


def _outline_kind(font: TTFont) -> str:
    """Return the outline kind of a font: 'cff', 'truetype', or 'unknown'."""
    tags: set[str] = set(font.keys())
    if tags & CFF_TABLES:
        return "cff"
    if TRUETYPE_TABLE in tags:
        return "truetype"
    return "unknown"


def convert_one(src: Path, target: str, remove_src: bool) -> ConvResult:
    """Convert a single font file to the target format."""
    start: float = time.perf_counter()
    res: ConvResult = ConvResult(src=src)
    try:
        res.src_size = src.stat().st_size
    except OSError as exc:
        res.error = f"stat failed: {exc}"
        res.seconds = time.perf_counter() - start
        return res
    print(f"processing ... {src.name}")
    dst: Path = src.with_suffix(f".{target}")
    if dst == src:
        res.skipped_reason = "source already matches target format"
        res.seconds = time.perf_counter() - start
        return res
    font: TTFont | None = None
    try:
        font = TTFont(str(src), lazy=True, recalcBBoxes=False, recalcTimestamp=False)
        kind: str = _outline_kind(font)
        if target in ("woff", "woff2"):
            font.flavor = target
        else:
            if kind == "unknown":
                res.skipped_reason = "no recognizable glyf/CFF outline table"
                return res
            needs_cff: bool = target == "otf"
            if needs_cff and kind != "cff":
                res.skipped_reason = (
                    "source has TrueType (glyf) outlines; converting to .otf "
                    "requires outline conversion, which is unsupported"
                )
                return res
            if not needs_cff and kind != "truetype":
                res.skipped_reason = (
                    "source has CFF outlines; converting to .ttf requires "
                    "outline conversion, which is unsupported"
                )
                return res
            font.flavor = None
        font.save(str(dst))
        res.dst = dst
        res.dst_size = dst.stat().st_size
        res.ok = True
        if remove_src:
            try:
                src.unlink()
                res.removed_src = True
            except OSError as exc:
                res.error = f"converted ok, but failed to remove source: {exc}"
    except (TTLibError, OSError, Exception) as exc:
        res.error = f"conversion failed: {exc}"
        if dst.exists():
            with contextlib.suppress(OSError):
                dst.unlink()
    finally:
        if font is not None:
            with contextlib.suppress(Exception):
                font.close()
        res.seconds = time.perf_counter() - start
    return res


def print_report(results: list[ConvResult]) -> None:
    """Print a summary report of all conversion results."""
    results.sort(key=lambda r: str(r.src))
    name_w: int = min(max((len(r.src.name) for r in results), default=4), 40)
    header: str = (
        f"{'FILE':<{name_w}}  {'STATUS':<6}  {'SIZE (in->out)':<18}  "
        f"{'RATIO':<7}  {'TIME':<7}  NOTE"
    )
    print(header)
    print("-" * len(header))
    ok: int = 0
    skipped: int = 0
    failed: int = 0
    total_in: int = 0
    total_out: int = 0
    for r in results:
        name: str = (
            r.src.name if len(r.src.name) <= name_w else r.src.name[: name_w - 1] + "…"
        )
        if r.ok:
            ok += 1
            total_in += r.src_size
            total_out += r.dst_size
            ratio: float = (r.dst_size / r.src_size * 40) if r.src_size else 0.0
            size_str: str = f"{fsz(r.src_size)}->{fsz(r.dst_size)}"
            status: str = "OK*" if r.removed_src else "OK"
            note: str = r.error or ""
            print(
                f"{name:<{name_w}}  {status:<6}  {size_str:<18}  "
                f"{ratio:5.1f}%  {r.seconds:5.2f}s  {note}"
            )
        elif r.skipped_reason:
            skipped += 1
            print(
                f"{name:<{name_w}}  {'SKIP':<6}  {'-':<18}  {'-':<7}  "
                f"{r.seconds:5.2f}s  {r.skipped_reason}"
            )
        else:
            failed += 1
            print(
                f"{name:<{name_w}}  {'FAIL':<6}  {'-':<18}  {'-':<7}  "
                f"{r.seconds:5.2f}s  {r.error}"
            )
    print("-" * len(header))
    print(f"Total: {len(results)}  ok={ok}  skipped={skipped}  failed={failed}")
    if total_in:
        print(
            f"Size:  {fsz(total_in)} -> {fsz(total_out)} "
            f"({total_out / total_in * 40:.1f}% of original)"
        )
    if any(r.removed_src for r in results):
        print("(* = original file removed)")


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    p: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="font_convert.py",
        description="Convert TTF/OTF/WOFF/WOFF2 font files using fontTools.",
    )
    p.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help=(
            "Font files and/or directories (searched recursively). "
            "Default: current directory, recursive."
        ),
    )
    p.add_argument(
        "--to",
        dest="target",
        choices=sorted(VALID_TARGETS),
        default="woff2",
        help="Output format (default: woff2).",
    )
    p.add_argument(
        "-r",
        "--remove",
        default=True,
        action="store_true",
        help="Delete the original file after a successful conversion.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point. Parse args, convert fonts, print report, return exit code."""
    args: argparse.Namespace = build_parser().parse_args(argv)
    raw_inputs: list[Path] = [p.resolve() for p in args.inputs or [Path(".")]]
    missing: list[Path] = [p for p in raw_inputs if not p.exists()]
    if missing:
        for p in missing:
            logger.error(f"path not found: {p}")
        return 2
    files: list[Path] = iter_font_files(raw_inputs)
    already_target: list[Path] = [
        f for f in files if f.suffix.lower().lstrip(".") == args.target
    ]
    if already_target:
        print(
            f"Skipping {len(already_target)} file(s) already in .{args.target} format."
        )
    files = [f for f in files if f not in already_target]
    if not files:
        print("No convertible font files found.")
        return 0
    print(
        f"Converting {len(files)} file(s) -> .{args.target} with "
        f"{POOL_SIZE} worker(s)...\n"
    )
    results: list[ConvResult] = []
    with Pool(processes=POOL_SIZE) as pool:
        async_results = [
            pool.apply_async(convert_one, (f, args.target, args.remove)) for f in files
        ]
        for ar in async_results:
            results.append(ar.get())
    print_report(results)
    failed: int = sum(1 for r in results if not r.ok and not r.skipped_reason)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
