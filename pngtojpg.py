#!/data/data/com.termux/files/home/.local/bin/python
"""
Recursively convert PNG images to JPEG.

- Backend priority: OpenCV (cv2) with an automatic Pillow fallback.
- Parallelised across a fixed pool of 8 workers using
  ``multiprocessing.Pool.imap_unordered`` for streaming results.
- Accepts any number of files/directories; with no arguments, walks the
  current working directory recursively.
- The original PNG is deleted only after the JPEG has been written
  successfully.
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Optional backend: prefer OpenCV, fall back to Pillow if unavailable.
# ---------------------------------------------------------------------------
try:
    import cv2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - environment dependent
    cv2 = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WORKERS: int = 8  # Fixed worker count (no CLI override by design).
DEFAULT_QUALITY: int = 95  # JPEG quality (0-100) for both backends.
BACKGROUND_RGB = (255, 255, 255)  # Used to flatten alpha channels for JPEG.


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------
def _convert_with_cv2(src: Path, dst: Path, quality: int) -> None:
    """
    Convert ``src`` (PNG) to ``dst`` (JPEG) using OpenCV.

    Uses ``imdecode`` / ``imencode`` rather than ``imread`` / ``imwrite``
    because the former handle non-ASCII paths (Windows, Android, etc.)
    correctly, while the latter silently fail on them.

    Alpha channels are composited over a white background because JPEG
    has no alpha channel.
    """
    # Read the entire file as a byte buffer, then decode in memory.
    buf = np.fromfile(str(src), dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"cv2 could not decode image: {src}")

    # Handle 4-channel images (BGRA): composite over white background.
    if img.ndim == 3 and img.shape[2] == 4:
        alpha = img[:, :, 3:4].astype(np.float32) / 255.0
        bgr = img[:, :, :3].astype(np.float32)
        white = np.full_like(bgr, 255.0)
        img = (bgr * alpha + white * (1.0 - alpha)).astype(np.uint8)

    # Single-channel grayscale -> expand to BGR so every JPEG is 3-channel.
    elif img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    ok, encoded = cv2.imencode(
        ".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]
    )
    if not ok:
        raise RuntimeError(f"cv2 failed to encode JPEG: {dst}")

    # ``tofile`` writes the encoded buffer directly, avoiding Python copies.
    encoded.tofile(str(dst))


def _convert_with_pillow(src: Path, dst: Path, quality: int) -> None:
    """
    Fallback conversion using Pillow.

    Handles RGBA / LA / P-with-transparency by compositing over a white
    background before saving as JPEG.
    """
    with Image.open(src) as img:
        has_alpha = img.mode in ("RGBA", "LA") or (
            img.mode == "P" and "transparency" in img.info
        )
        if has_alpha:
            rgba = img.convert("RGBA")
            bg = Image.new("RGB", rgba.size, BACKGROUND_RGB)
            # ``paste`` with the alpha channel as mask performs the composite.
            bg.paste(rgba, mask=rgba.split()[-1])
            rgb = bg
        else:
            rgb = img.convert("RGB")

        rgb.save(dst, "JPEG", quality=quality, optimize=True)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
def _convert_one(png_path: Path) -> tuple[Path, bool, str]:
    """
    Convert a single PNG file to JPEG and delete the original on success.

    Returns:
        ``(source_path, success, message)`` so the parent process can
        report streaming progress via ``imap_unordered``.
    """
    jpg_path = png_path.with_suffix(".jpg")

    # 1) Perform the conversion.
    try:
        if cv2 is not None:
            _convert_with_cv2(png_path, jpg_path, DEFAULT_QUALITY)
        else:
            _convert_with_pillow(png_path, jpg_path, DEFAULT_QUALITY)
    except Exception as exc:  # noqa: BLE001 - we want to report any failure
        return png_path, False, f"{type(exc).__name__}: {exc}"

    # 2) Only remove the source after the destination was written.
    try:
        png_path.unlink()
    except OSError as exc:
        return (
            png_path,
            True,
            f"converted -> {jpg_path} (warning: could not delete original: {exc})",
        )

    return png_path, True, str(jpg_path)


# ---------------------------------------------------------------------------
# Input discovery
# ---------------------------------------------------------------------------
def collect_png_files(inputs: list[str]) -> list[Path]:
    """
    Expand CLI inputs into a deduplicated list of PNG paths.

    - Directories are walked recursively via ``Path.rglob("*.png")``.
    - Explicitly provided files are included regardless of extension
      (the user asked for them explicitly).
    - If ``inputs`` is empty, the current directory is used.
    """
    if not inputs:
        inputs = ["."]

    found: list[Path] = []
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            found.extend(sorted(p.rglob("*.png")))
        elif p.is_file():
            found.append(p)
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
    """Entry point: parse arguments and run the conversion pool."""
    parser = argparse.ArgumentParser(
        description=(
            "Recursively convert PNG files to JPEG. Accepts one or more "
            "files/directories. With no arguments, walks the current "
            "directory recursively. Deletes the original PNG after a "
            "successful conversion."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Files or directories to process (default: current directory).",
    )
    args = parser.parse_args()

    png_files = collect_png_files(args.inputs)
    if not png_files:
        print("No PNG files found.", file=sys.stderr)
        return 1

    backend = "cv2" if cv2 is not None else "Pillow"
    print(
        f"Converting {len(png_files)} file(s) with {WORKERS} workers "
        f"(backend: {backend})..."
    )

    failures = 0

    # ``imap_unordered`` streams results as tasks finish, which keeps the
    # parent responsive and avoids buffering all results in memory.
    with mp.Pool(processes=WORKERS) as pool:
        for src, ok, msg in pool.imap_unordered(_convert_one, png_files):
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
    # ``raise SystemExit`` propagates the exit code without an extra stack.
    raise SystemExit(main())
