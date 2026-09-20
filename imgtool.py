#!/data/data/com.termux/files/home/.local/bin/python
"""
imgtool.py — Unified image / HTML conversion toolkit.

This single script merges the behaviour of 13 small scripts into one CLI with
subcommands.  Every original script's behaviour is reachable.

Subcommand mapping
------------------
avif2jpg.py    ->  python imgtool.py to-jpg avif_images --output jpg_images \
                                       --ext .avif .aviff
heif2jpg.py    ->  python imgtool.py to-jpg --ext .heif .heic
png2jpg.py     ->  python imgtool.py to-jpg --ext .png --delete-source [paths ...]
pngtojpg.py    ->  python imgtool.py to-jpg --ext .png --delete-source
to_jpg.py      ->  python imgtool.py to-jpg --delete-source [paths ...]
tojpg.py       ->  python imgtool.py to-jpg FILE --delete-source
svg2png.py     ->  python imgtool.py to-png --ext .svg
to_png.py      ->  python imgtool.py to-png --delete-source
topng.py       ->  python imgtool.py to-png FILE --delete-source
gif2jpg.py     ->  python imgtool.py gif-to-jpg
neg.py         ->  python imgtool.py invert DIR [--dry-run] [-w N]
htm2png.py     ->  python imgtool.py html-to-png --method cairosvg
html2png.py    ->  python imgtool.py html-to-png --method pdf2image DIR OUT

Dependencies
------------
Required    : Pillow
Optional    : numpy, opencv-python, pillow-heif, cairosvg,
              weasyprint, pdf2image, joblib
"""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, Optional, Sequence

# ============================================================================
# Optional dependency imports
# ============================================================================
try:
    from PIL import Image, UnidentifiedImageError  # type: ignore

    _HAS_PIL = True
except ImportError:  # pragma: no cover
    Image = None  # type: ignore
    UnidentifiedImageError = Exception  # type: ignore
    _HAS_PIL = False

try:
    import numpy as np  # type: ignore

    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    np = None  # type: ignore
    _HAS_NUMPY = False

try:
    import cv2  # type: ignore

    _HAS_CV2 = True
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore
    _HAS_CV2 = False

try:
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
    _HAS_HEIF = True
except ImportError:  # pragma: no cover
    _HAS_HEIF = False

try:
    import cairosvg  # type: ignore

    _HAS_CAIROSVG = True
except ImportError:  # pragma: no cover
    cairosvg = None  # type: ignore
    _HAS_CAIROSVG = False

try:
    from weasyprint import HTML  # type: ignore

    _HAS_WEASYPRINT = True
except ImportError:  # pragma: no cover
    HTML = None  # type: ignore
    _HAS_WEASYPRINT = False

try:
    from pdf2image import convert_from_bytes  # type: ignore

    _HAS_PDF2IMAGE = True
except ImportError:  # pragma: no cover
    convert_from_bytes = None  # type: ignore
    _HAS_PDF2IMAGE = False


# ============================================================================
# Logging
# ============================================================================
LOG = logging.getLogger("imgtool")


def setup_logging(verbose: bool = False) -> None:
    """Configure root logging exactly like the original gif2jpg.py did."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


# ============================================================================
# Constants (defaults preserved from the original scripts)
# ============================================================================
DEFAULT_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "dist",
        "build",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "node_modules",
        ".idea",
        ".vscode",
    }
)

# to_jpg.py / tojpg.py union plus avif & heif
JPG_INPUT_EXTS: frozenset[str] = frozenset(
    {
        ".png",
        ".bmp",
        ".tiff",
        ".tif",
        ".webp",
        ".ico",
        ".jpeg",
        ".jpg",
        ".avif",
        ".aviff",
        ".heif",
        ".heic",
        ".ppm",
        ".pgm",
    }
)

# to_png.py union plus svg
PNG_INPUT_EXTS: frozenset[str] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".bmp",
        ".tif",
        ".tiff",
        ".webp",
        ".gif",
        ".ppm",
        ".pgm",
        ".svg",
        ".ico",
    }
)

# neg.py default extension set
INVERT_EXTS: frozenset[str] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".tiff",
        ".tif",
        ".webp",
        ".gif",
    }
)


# ============================================================================
# Generic helpers
# ============================================================================
def find_files(
    roots: Sequence[Path],
    extensions: Optional[Iterable[str]] = None,
    recursive: bool = True,
    exclude_dirs: frozenset[str] = DEFAULT_EXCLUDE_DIRS,
) -> list[Path]:
    """Return a sorted list of unique files under *roots*.

    *extensions* (if given) is matched case-insensitively on the suffix.
    Directories whose name appears in *exclude_dirs* are skipped.
    """
    exts = {e.lower() for e in extensions} if extensions else None
    results: list[Path] = []
    seen: set[Path] = set()

    def _add(p: Path) -> None:
        try:
            rp = p.resolve()
        except OSError:
            return
        if rp in seen:
            return
        seen.add(rp)
        results.append(p)

    for root in roots:
        if root.is_file():
            if exts is None or root.suffix.lower() in exts:
                _add(root)
            continue
        if not root.is_dir():
            LOG.warning("Not a file or directory: %s", root)
            continue

        iterator = root.rglob("*") if recursive else root.iterdir()
        for f in iterator:
            try:
                if not f.is_file():
                    continue
            except OSError:
                continue
            if any(part in exclude_dirs for part in f.parts):
                continue
            if exts is not None and f.suffix.lower() not in exts:
                continue
            _add(f)

    results.sort()
    return results


def dir_size(path: Path) -> int:
    """Total size of *path* in bytes (recursive for directories)."""
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def human_size(n: int) -> str:
    """Human readable byte size (matches typical 'K/M/G' formatting)."""
    sign = "-" if n < 0 else ""
    n = abs(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{sign}{n:.2f} {unit}"
        n /= 1024.0
    return f"{sign}{n:.2f} PB"


def _run_parallel(
    worker,
    tasks: list,
    workers: int,
) -> list:
    """Execute *worker(task)* for every task, sequentially when workers==1."""
    if not tasks:
        return []
    if workers == 1:
        return [worker(t) for t in tasks]

    results: list = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(worker, t) for t in tasks]
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as exc:  # pragma: no cover
                LOG.error("Worker raised: %s", exc)
    return results


# ============================================================================
# Image helpers
# ============================================================================
def flatten_to_rgb(im: "Image.Image", bg=(255, 255, 255)) -> "Image.Image":
    """Flatten an image with transparency onto a solid background."""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        canvas = Image.new("RGB", im.size, bg)
        canvas.paste(im, mask=im.split()[-1])
        return canvas
    if im.mode != "RGB":
        return im.convert("RGB")
    return im


def save_jpeg(src: Path, dst: Path, quality: int = 95, backend: str = "auto") -> None:
    """Convert *src* to JPEG at *dst*; honours alpha by flattening onto white."""
    # Optional fast path with OpenCV (matches to_jpg.py / tojpg.py behaviour)
    if backend in ("auto", "cv2") and _HAS_CV2:
        img = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
        if img is not None:
            if img.ndim == 3 and img.shape[2] == 4:
                b, g, r, a = cv2.split(img)
                alpha = a.astype("float") / 255.0
                bg = np.full(img.shape[:2], 255, dtype=np.uint8).astype("float")
                b = (b.astype("float") * alpha + bg * (1 - alpha)).astype("uint8")
                g = (g.astype("float") * alpha + bg * (1 - alpha)).astype("uint8")
                r = (r.astype("float") * alpha + bg * (1 - alpha)).astype("uint8")
                img = cv2.merge((b, g, r))
            ok = cv2.imwrite(str(dst), img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
            if ok:
                return
            if backend == "cv2":
                raise IOError(f"cv2 failed to write {dst}")

    if not _HAS_PIL:
        raise RuntimeError("Pillow is required for JPEG output")
    with Image.open(src) as im:
        im = flatten_to_rgb(im)
        im.save(dst, "JPEG", quality=quality, optimize=True)


def save_png(
    src: Path, dst: Path, backend: str = "auto", preserve_alpha: bool = False
) -> None:
    """Convert *src* to PNG at *dst*."""
    # SVG requires a dedicated renderer
    if src.suffix.lower() == ".svg":
        if not _HAS_CAIROSVG:
            raise RuntimeError("cairosvg is required to render SVG files")
        cairosvg.svg2png(url=str(src), write_to=str(dst))
        return

    if backend in ("auto", "cv2") and _HAS_CV2:
        img = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
        if img is not None:
            if img.ndim == 3 and img.shape[2] == 4 and not preserve_alpha:
                b, g, r, a = cv2.split(img)
                alpha = a.astype("float") / 255.0
                bg = np.full(img.shape[:2], 255, dtype=np.uint8).astype("float")
                b = (b.astype("float") * alpha + bg * (1 - alpha)).astype("uint8")
                g = (g.astype("float") * alpha + bg * (1 - alpha)).astype("uint8")
                r = (r.astype("float") * alpha + bg * (1 - alpha)).astype("uint8")
                img = cv2.merge((b, g, r))
            if cv2.imwrite(str(dst), img):
                return
            if backend == "cv2":
                raise IOError(f"cv2 failed to write {dst}")

    if not _HAS_PIL:
        raise RuntimeError("Pillow is required for PNG output")
    with Image.open(src) as im:
        if not preserve_alpha:
            im = flatten_to_rgb(im)
        elif im.mode not in ("RGB", "RGBA", "L", "LA", "P"):
            im = im.convert("RGBA")
        im.save(dst, "PNG")


# ============================================================================
# Worker functions (module level for ProcessPoolExecutor pickling)
# ============================================================================
def _worker_jpg(task):
    src, dst, quality, backend, delete_source = task
    try:
        save_jpeg(src, dst, quality=quality, backend=backend)
    except Exception as exc:
        return (str(src), False, f"{src.name} -> {dst.name}: {exc}")
    if delete_source:
        try:
            src.unlink()
        except OSError as exc:
            return (
                str(src),
                False,
                f"wrote {dst.name} but could not delete {src.name}: {exc}",
            )
    return (str(src), True, f"{src.name} -> {dst.name}")


def _worker_png(task):
    src, dst, backend, delete_source, preserve_alpha = task
    try:
        save_png(src, dst, backend=backend, preserve_alpha=preserve_alpha)
    except Exception as exc:
        return (str(src), False, f"{src.name} -> {dst.name}: {exc}")
    if delete_source:
        try:
            src.unlink()
        except OSError as exc:
            return (
                str(src),
                False,
                f"wrote {dst.name} but could not delete {src.name}: {exc}",
            )
    return (str(src), True, f"{src.name} -> {dst.name}")


def _worker_invert(task):
    src, dry_run = task
    if dry_run:
        return (str(src), True, f"[DRY RUN] would invert {src}")
    if not _HAS_PIL:
        return (str(src), False, "Pillow is required for invert")
    try:
        with Image.open(src) as im:
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            out = im.point(lambda p: 255 - p)
            out.save(src, quality=95, optimize=True)
        return (str(src), True, f"inverted {src}")
    except Exception as exc:
        return (str(src), False, f"failed {src}: {exc}")


def _extract_gif_frames(
    path: Path, dup_mean: float, dup_frac: float
) -> list["np.ndarray"]:
    """Extract GIF frames, honouring disposal modes and skipping dupes.

    This is a faithful port of gif2jpg.py's `p()`.
    """
    if not (_HAS_PIL and _HAS_NUMPY):
        raise RuntimeError("Pillow + numpy are required for GIF extraction")

    def is_dup(a, b) -> bool:
        if a.shape != b.shape:
            return False
        diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
        return diff.mean() < dup_mean and (diff > 10).any(axis=-1).mean() < dup_frac

    frames: list = []
    try:
        with Image.open(path) as img:
            # Non-animated image disguised as .gif
            if not hasattr(img, "n_frames"):
                canvas = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode in ("RGBA", "P"):
                    rgba = img.convert("RGBA")
                    canvas.paste(rgba, mask=rgba.split()[3])
                else:
                    canvas.paste(img.convert("RGB"))
                frames.append(np.asarray(canvas))
                return frames

            canvas = Image.new("RGB", img.size, (255, 255, 255))
            prev = None
            for idx in range(img.n_frames):
                img.seek(idx)
                disposal = img.info.get("disposal", 0)
                if disposal == 3 and prev is not None:
                    canvas = prev.copy()
                elif disposal == 2:
                    canvas = Image.new("RGB", img.size, (255, 255, 255))
                prev = canvas.copy()
                rgba = img.convert("RGBA")
                canvas.paste(rgba, mask=rgba.split()[3])
                arr = np.asarray(canvas.convert("RGB"))
                if frames and is_dup(frames[-1], arr):
                    LOG.debug(
                        "  skipping near-duplicate frame %d in %s", idx, path.name
                    )
                    continue
                frames.append(arr)
    except (UnidentifiedImageError, OSError) as exc:
        LOG.error("Cannot open %s: %s", path, exc)
    return frames


def _worker_gif(task):
    src, quality, dup_mean, dup_frac, overwrite = task
    try:
        frames = _extract_gif_frames(src, dup_mean, dup_frac)
    except Exception as exc:
        return (str(src), False, f"{src.name}: {exc}")
    if not frames:
        return (str(src), False, f"no usable frames in {src}")

    stem = src.stem
    parent = src.parent
    pad = len(str(len(frames)))
    written = 0
    for idx, arr in enumerate(frames):
        if len(frames) == 1:
            dst = parent / f"{stem}.jpg"
        else:
            dst = parent / f"{stem}_frame{idx:0{pad}d}.jpg"
        if dst.exists() and not overwrite:
            continue
        try:
            im = Image.fromarray(arr, mode="RGB")
            im.save(dst, format="JPEG", quality=quality, optimize=True)
            written += 1
        except OSError as exc:
            LOG.error("Failed to save %s: %s", dst, exc)
    return (str(src), True, f"{src.name}: {written} frame(s) -> JPG")


# ============================================================================
# Subcommand implementations
# ============================================================================
def cmd_to_jpg(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in args.paths] if args.paths else [Path.cwd()]
    exts = {e.lower() for e in args.ext} if args.ext else set(JPG_INPUT_EXTS)

    files = find_files(paths, exts, recursive=args.recursive)
    if not files:
        LOG.warning("No matching input files found.")
        return 0

    out_dir = Path(args.output) if args.output else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    tasks = []
    for src in files:
        if src.suffix.lower() in (".jpg", ".jpeg"):
            continue  # already JPEG
        dst = (out_dir / (src.stem + ".jpg")) if out_dir else src.with_suffix(".jpg")
        if dst.exists() and not args.overwrite:
            LOG.debug("skip (exists): %s", dst)
            continue
        tasks.append((src, dst, args.quality, args.backend, args.delete_source))

    if not tasks:
        LOG.info("Nothing to do.")
        return 0

    LOG.info("Converting %d file(s) to JPEG (%d worker(s))…", len(tasks), args.workers)
    results = _run_parallel(_worker_jpg, tasks, args.workers)

    ok = sum(1 for _, s, _ in results if s)
    fail = len(results) - ok
    LOG.info("Done. %d succeeded, %d failed.", ok, fail)
    return 0 if fail == 0 else 1


def cmd_to_png(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in args.paths] if args.paths else [Path.cwd()]
    exts = {e.lower() for e in args.ext} if args.ext else set(PNG_INPUT_EXTS)

    files = find_files(paths, exts, recursive=args.recursive)
    if not files:
        LOG.warning("No matching input files found.")
        return 0

    out_dir = Path(args.output) if args.output else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    tasks = []
    for src in files:
        if src.suffix.lower() == ".png":
            continue
        dst = (out_dir / (src.stem + ".png")) if out_dir else src.with_suffix(".png")
        if dst.exists() and not args.overwrite:
            LOG.debug("skip (exists): %s", dst)
            continue
        tasks.append((src, dst, args.backend, args.delete_source, args.preserve_alpha))

    if not tasks:
        LOG.info("Nothing to do.")
        return 0

    LOG.info("Converting %d file(s) to PNG (%d worker(s))…", len(tasks), args.workers)
    results = _run_parallel(_worker_png, tasks, args.workers)

    ok = sum(1 for _, s, _ in results if s)
    fail = len(results) - ok
    LOG.info("Done. %d succeeded, %d failed.", ok, fail)
    return 0 if fail == 0 else 1


def cmd_gif_to_jpg(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in args.paths] if args.paths else [Path.cwd()]
    files = find_files(paths, {".gif"}, recursive=args.recursive)
    if not files:
        LOG.info("No GIF files found.")
        return 0

    LOG.info("Found %d GIF file(s). Converting…", len(files))
    tasks = [
        (f, args.quality, args.dup_mean, args.dup_frac, args.overwrite) for f in files
    ]
    results = _run_parallel(_worker_gif, tasks, args.workers)

    ok = sum(1 for _, s, _ in results if s)
    fail = len(results) - ok
    LOG.info("Done. %d GIF(s) processed, %d failed.", ok, fail)
    return 0 if fail == 0 else 1


def cmd_invert(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in args.paths] if args.paths else [Path.cwd()]
    exts = {e.lower() for e in args.ext} if args.ext else set(INVERT_EXTS)

    files = find_files(paths, exts, recursive=args.recursive)
    if not files:
        LOG.warning("No image files found to invert.")
        return 0

    LOG.info(
        "Inverting %d file(s) (%d worker(s))%s…",
        len(files),
        args.workers,
        " [DRY RUN]" if args.dry_run else "",
    )
    tasks = [(f, args.dry_run) for f in files]
    results = _run_parallel(_worker_invert, tasks, args.workers)

    ok = sum(1 for _, s, _ in results if s)
    fail = len(results) - ok
    LOG.info("Done. %d succeeded, %d failed.", ok, fail)
    return 0 if fail == 0 else 1


def _html_to_png(
    src: str, dst: Path, method: str, width: Optional[int], dpi: int, scale: float
) -> None:
    """Render *src* (file path or HTML string) to PNG at *dst*.

    Two rendering methods are supported:
      * ``cairosvg``  — HTML → PDF → PNG via cairosvg (htm2png.py behaviour)
      * ``pdf2image`` — HTML → PDF → PIL pages, vertically stitched
                        (html2png.py behaviour)
    """
    if not _HAS_WEASYPRINT:
        raise RuntimeError("weasyprint is required for HTML rendering")

    if src.lstrip().startswith("<"):
        html = HTML(string=src)
    else:
        html = HTML(filename=src)

    pdf_bytes = html.write_pdf()

    if method == "cairosvg":
        if not _HAS_CAIROSVG:
            raise RuntimeError("cairosvg is required for method='cairosvg'")
        cairosvg.svg2png(
            bytestring=pdf_bytes, write_to=str(dst), output_width=width, scale=scale
        )
    elif method == "pdf2image":
        if not _HAS_PDF2IMAGE:
            raise RuntimeError("pdf2image is required for method='pdf2image'")
        pages = convert_from_bytes(pdf_bytes, dpi=dpi)
        if len(pages) > 1:
            total_h = sum(p.height for p in pages)
            max_w = max(p.width for p in pages)
            canvas = Image.new("RGB", (max_w, total_h), (255, 255, 255))
            y = 0
            for page in pages:
                canvas.paste(page, (0, y))
                y += page.height
            canvas.save(dst, "PNG")
        else:
            pages[0].save(dst, "PNG")
    else:
        raise ValueError(f"Unknown HTML render method: {method}")


def cmd_html_to_png(args: argparse.Namespace) -> int:
    if not _HAS_WEASYPRINT:
        LOG.error("weasyprint is required for html-to-png (pip install weasyprint)")
        return 1

    paths = [Path(p) for p in args.paths] if args.paths else [Path.cwd()]
    out_dir = Path(args.output) if args.output else None

    # Collect .html files (or raw HTML strings passed directly)
    inputs: list[str] = []
    for p in paths:
        if isinstance(p, Path) and p.is_dir():
            for f in sorted(p.glob("*.html")):
                inputs.append(str(f))
        elif isinstance(p, Path) and p.is_file():
            inputs.append(str(p))
        else:
            inputs.append(str(p))  # literal HTML string

    if not inputs:
        LOG.warning("No HTML inputs found.")
        return 0

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    ok = fail = 0
    for src in inputs:
        if src.startswith("<"):
            stem = "inline"
        else:
            stem = Path(src).stem
        dst = (out_dir / f"{stem}.png") if out_dir else Path(f"{stem}.png")
        try:
            _html_to_png(src, dst, args.method, args.width, args.dpi, args.scale)
            LOG.info("PNG saved to: %s", dst)
            ok += 1
        except Exception as exc:
            LOG.error("Failed to render %s: %s", src, exc)
            fail += 1

    LOG.info("Done. %d succeeded, %d failed.", ok, fail)
    return 0 if fail == 0 else 1


# ============================================================================
# Argument parser
# ============================================================================
def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "paths", nargs="*", help="Files or directories (default: current directory)."
    )
    p.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        default=True,
        help="Recurse into subdirectories (default).",
    )
    p.add_argument(
        "--no-recursive",
        dest="recursive",
        action="store_false",
        help="Do not recurse into subdirectories.",
    )
    p.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output directory (default: alongside the source).",
    )
    p.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing output files."
    )
    p.add_argument(
        "-w",
        "--workers",
        type=int,
        default=0,
        help="Worker processes (0 = CPU count, 1 = sequential).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="imgtool",
        description="Unified image & HTML conversion toolkit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  imgtool to-jpg photos/ --delete-source\n"
            "  imgtool to-jpg avif_images --output jpg_images --ext .avif .aviff\n"
            "  imgtool to-png svg_dir --ext .svg\n"
            "  imgtool gif-to-jpg anim/\n"
            "  imgtool invert ./pics --dry-run -w 4\n"
            "  imgtool html-to-png page.html --method pdf2image --dpi 200\n"
        ),
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging."
    )
    sub = parser.add_subparsers(dest="command")

    # --- to-jpg ------------------------------------------------------------
    p = sub.add_parser("to-jpg", aliases=["jpg"], help="Convert images to JPEG.")
    _add_common(p)
    p.add_argument(
        "--ext",
        nargs="*",
        default=None,
        help="Input extensions (default: common raster + avif/heif).",
    )
    p.add_argument(
        "--quality", type=int, default=95, help="JPEG quality 1-100 (default: 95)."
    )
    p.add_argument(
        "--backend",
        choices=("auto", "cv2", "pil"),
        default="auto",
        help="Image backend (default: auto).",
    )
    p.add_argument(
        "--delete-source",
        action="store_true",
        help="Delete the source file after a successful conversion.",
    )
    p.set_defaults(func=cmd_to_jpg)

    # --- to-png ------------------------------------------------------------
    p = sub.add_parser("to-png", aliases=["png"], help="Convert images to PNG.")
    _add_common(p)
    p.add_argument(
        "--ext",
        nargs="*",
        default=None,
        help="Input extensions (default: common raster + svg).",
    )
    p.add_argument(
        "--backend",
        choices=("auto", "cv2", "pil"),
        default="auto",
        help="Image backend (default: auto).",
    )
    p.add_argument(
        "--delete-source",
        action="store_true",
        help="Delete the source file after a successful conversion.",
    )
    p.add_argument(
        "--preserve-alpha",
        action="store_true",
        help="Keep alpha channel instead of flattening onto white.",
    )
    p.set_defaults(func=cmd_to_png)

    # --- gif-to-jpg --------------------------------------------------------
    p = sub.add_parser(
        "gif-to-jpg", aliases=["gif"], help="Extract GIF frames as JPEGs."
    )
    _add_common(p)
    p.add_argument(
        "--quality", type=int, default=90, help="JPEG quality (default: 90)."
    )
    p.add_argument(
        "--dup-mean",
        type=float,
        default=8.0,
        help="Mean-diff threshold for dup detection (default: 8.0).",
    )
    p.add_argument(
        "--dup-frac",
        type=float,
        default=0.005,
        help="Fraction of large-diff pixels for dup detection (default: 0.005).",
    )
    p.add_argument(
        "--keep-duplicates",
        dest="drop_dupes",
        action="store_false",
        default=True,
        help="Keep near-duplicate frames (disable deduplication).",
    )
    p.set_defaults(func=cmd_gif_to_jpg)

    # --- invert ------------------------------------------------------------
    p = sub.add_parser("invert", help="Invert image colours (negative) in place.")
    _add_common(p)
    p.add_argument(
        "--ext",
        nargs="*",
        default=None,
        help="Extensions to process (default: common image types).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without modifying files.",
    )
    p.set_defaults(func=cmd_invert)

    # --- html-to-png -------------------------------------------------------
    p = sub.add_parser(
        "html-to-png",
        aliases=["html"],
        help="Render HTML (file, dir, or inline string) to PNG.",
    )
    p.add_argument(
        "paths", nargs="*", help="HTML files, directories, or inline HTML strings."
    )
    p.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output directory (default: current directory).",
    )
    p.add_argument(
        "--method",
        choices=("cairosvg", "pdf2image"),
        default="pdf2image",
        help="Rendering pipeline (default: pdf2image).",
    )
    p.add_argument(
        "--width",
        type=int,
        default=None,
        help="Output width in pixels (cairosvg method only).",
    )
    p.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="Rendering DPI for pdf2image (default: 150).",
    )
    p.add_argument(
        "--scale", type=float, default=2.0, help="cairosvg scale factor (default: 2.0)."
    )
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_html_to_png)

    return parser


# ============================================================================
# Entry point
# ============================================================================
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 2

    # Resolve worker count now that the parser knows about it
    if hasattr(args, "workers") and (args.workers is None or args.workers <= 0):
        try:
            import os

            args.workers = os.cpu_count() or 1
        except Exception:  # pragma: no cover
            args.workers = 1

    setup_logging(getattr(args, "verbose", False))
    try:
        return args.func(args)
    except KeyboardInterrupt:  # pragma: no cover
        LOG.warning("Interrupted.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
