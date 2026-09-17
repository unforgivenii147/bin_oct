#!/data/data/com.termux/files/home/.local/bin/python
"""
Recursively convert AVIF images to JPEG.

Highlights
----------
- Uses ``pathlib`` exclusively for path handling.
- Parallelised with ``multiprocessing.Pool.starmap`` using a fixed pool of
  8 workers (no CLI override, by design).
- Accepts any number of files and/or directories. With no arguments, the
  current working directory is walked recursively.
- Output file is written *next to* the source using
  ``fname.with_suffix('.jpg')``.
- Targets Python 3.12.
- AVIF decoding requires a Pillow build with AVIF support (Pillow >= 11.3,
  or the ``pillow-avif-plugin`` package). If AVIF cannot be decoded, the
  failure is reported per-file without killing the pool.
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# ---------------------------------------------------------------------------
# Optional AVIF plugin registration.
#
# Newer Pillow releases include AVIF support natively. On older releases,
# the ``pillow-avif-plugin`` package must be installed and imported so its
# decoder is registered with Pillow. We import it defensively so the script
# still runs (and reports a clear error) when the decoder is missing.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - environment dependent
    import pillow_avif  # type: ignore[import-not-found]  # noqa: F401
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WORKERS: int = 8  # Fixed worker count (no CLI toggle by design).
DEFAULT_QUALITY: int = 95  # JPEG quality (0-100).
AVIF_SUFFIXES: frozenset[str] = frozenset({".avif", ".aviff"})
BACKGROUND_RGB: tuple[int, int, int] = (255, 255, 255)  # For alpha flattening.


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
def convert_one(
    src: Path,
    dst: Path,
    quality: int = DEFAULT_QUALITY,
) -> tuple[Path, bool, str]:
    """
    Convert a single AVIF file to JPEG.

    The destination filename is derived from the source by replacing the
    suffix with ``.jpg`` (handled by the caller). The source file is left
    untouched (this script does not delete inputs).

    Args:
        src:     Source AVIF path.
        dst:     Destination JPEG path.
        quality: JPEG quality (0-100).

    Returns:
        ``(src, success, message)`` — designed to be fed straight into
        ``Pool.starmap`` and printed by the parent process.
    """
    try:
        # ``with`` ensures the file handle is closed even on exceptions.
        with Image.open(src) as img:
            # JPEG has no alpha channel; composite RGBA/LA/P-with-transparency
            # over a solid white background for a clean result.
            has_alpha = img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            )

            if has_alpha:
                rgba = img.convert("RGBA")
                bg = Image.new("RGB", rgba.size, BACKGROUND_RGB)
                # Use the alpha channel as the paste mask.
                bg.paste(rgba, mask=rgba.split()[-1])
                rgb = bg
            else:
                rgb = img.convert("RGB")

            # ``optimize=True`` produces smaller files at a tiny CPU cost.
            rgb.save(dst, "JPEG", quality=quality, optimize=True)
    except (UnidentifiedImageError, OSError) as exc:
        # Known, expected failure modes: bad/unsupported AVIF, unreadable file.
        return src, False, f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 - report anything unexpected too
        return src, False, f"{type(exc).__name__}: {exc}"

    return src, True, str(dst)


# ---------------------------------------------------------------------------
# Input discovery
# ---------------------------------------------------------------------------
def collect_avif_files(inputs: list[str]) -> list[Path]:
    """
    Expand CLI inputs into a deduplicated list of AVIF paths.

    Behaviour:
        - Directories are walked recursively via ``Path.rglob('*')`` and
          filtered by suffix.
        - Explicitly named files are included if their suffix looks like
          AVIF; anything else triggers a warning and is skipped.
        - When ``inputs`` is empty, the current directory is used.
    """
    if not inputs:
        inputs = ["."]

    found: list[Path] = []
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            # ``rglob('*')`` matches every entry; filter by suffix + is_file.
            found.extend(
                f
                for f in sorted(p.rglob("*"))
                if f.is_file() and f.suffix.lower() in AVIF_SUFFIXES
            )
        elif p.is_file():
            if p.suffix.lower() in AVIF_SUFFIXES:
                found.append(p)
            else:
                print(
                    f"warning: skipping non-AVIF file: {p}",
                    file=sys.stderr,
                )
        else:
            print(f"warning: skipping non-existent path: {p}", file=sys.stderr)

    # Deduplicate by resolved path while preserving discovery order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for f in found:
        rp = f.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(f)
    return unique


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    """Parse arguments and run the conversion pool."""
    parser = argparse.ArgumentParser(
        description=(
            "Recursively convert AVIF images to JPEG. Accepts one or more "
            "files/directories. With no arguments, walks the current "
            "directory recursively. Each JPEG is written next to its "
            "source with a .jpg suffix."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Files or directories to process (default: current directory).",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=DEFAULT_QUALITY,
        help=f"JPEG quality 0-100 (default: {DEFAULT_QUALITY}).",
    )
    args = parser.parse_args()

    # Clamp quality defensively so a bad value can't silently corrupt output.
    quality = max(1, min(100, args.quality))

    avif_files = collect_avif_files(args.inputs)
    if not avif_files:
        print("No AVIF files found.", file=sys.stderr)
        return 1

    # Build the (src, dst, quality) tuples consumed by ``starmap``.
    # ``with_suffix`` replaces the existing suffix (e.g. ".avif") with ".jpg".
    tasks: list[tuple[Path, Path, int]] = [
        (src, src.with_suffix(".jpg"), quality) for src in avif_files
    ]

    print(
        f"Converting {len(tasks)} file(s) with {WORKERS} workers (quality={quality})..."
    )

    # ``starmap`` unpacks each 3-tuple as positional args to ``convert_one``.
    # It blocks until every task is done, returning results in input order.
    with mp.Pool(processes=WORKERS) as pool:
        results = pool.starmap(convert_one, tasks)

    failures = 0
    for src, ok, msg in results:
        if ok:
            print(f"OK   {src} -> {msg}")
        else:
            failures += 1
            print(f"FAIL {src}: {msg}", file=sys.stderr)

    if failures:
        print(f"{failures} file(s) failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    # ``raise SystemExit`` propagates the exit code without extra stack noise.
    raise SystemExit(main())
