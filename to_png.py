#!/data/data/com.termux/files/home/.local/bin/python
"""
Convert image files under the current directory to PNG, trying conversion
backends in priority order: OpenCV (cv2), then scikit-image, then Pillow.
Alpha channels are composited onto a white background before saving. Source
files are deleted on success. Files are processed via a fixed
multiprocessing.Pool of 8 workers. Logging via loguru.
"""

from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Any, Final

from dh import fsz, gsz, is_image  # type: ignore[import-untyped]
from loguru import logger

MAX_WORKERS: Final[int] = 8

# Image extensions this script converts (everything that isn't already .png).
IMGEXT: Final[frozenset[str]] = frozenset(
    {".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif", ".ppm", ".pgm"}
)
IGNORED_DIRS: Final[frozenset[str]] = frozenset(
    {".git", "dist", "build", "__pycache__", ".venv", "node_modules"}
)

# --- Backend probing (cv2 -> skimage -> Pillow) ---------------------------------

_CV2_AVAILABLE: bool = False
_SKIMAGE_AVAILABLE: bool = False
_PIL_AVAILABLE: bool = False

cv2: Any = None
np: Any = None
skio: Any = None
Image: Any = None

try:
    import cv2 as _cv2
    import numpy as _np

    cv2 = _cv2
    np = _np
    _CV2_AVAILABLE = True
except ImportError:
    pass

if not _CV2_AVAILABLE:
    try:
        import numpy as _np2
        import skimage.io as _skio

        skio = _skio
        np = _np2
        _SKIMAGE_AVAILABLE = True
    except ImportError:
        pass

if not _CV2_AVAILABLE and not _SKIMAGE_AVAILABLE:
    try:
        from PIL import Image as _PILImage

        Image = _PILImage
        _PIL_AVAILABLE = True
    except ImportError:
        pass


ConvertResult = tuple[Path, bool, str]


# --- Backend-specific converters -----------------------------------------------


def _composite_alpha_cv2(img: Any) -> Any:
    """
    Composite the alpha channel of a BGRA cv2 image onto a white background.

    Args:
        img: The cv2 image (H, W, 3) or (H, W, 4).

    Returns:
        A BGR image with no alpha channel.
    """
    if img.shape[2] != 4:
        return img
    b, g, r, a = cv2.split(img)
    white_bg = np.full(img.shape[:2], 255, dtype=np.uint8)
    alpha = a.astype(float) / 255.0
    inv = 1 - alpha
    img_b = (b.astype(float) * alpha + white_bg.astype(float) * inv).astype(np.uint8)
    img_g = (g.astype(float) * alpha + white_bg.astype(float) * inv).astype(np.uint8)
    img_r = (r.astype(float) * alpha + white_bg.astype(float) * inv).astype(np.uint8)
    return cv2.merge((img_b, img_g, img_r))


def _convert_cv2(path: Path, output_path: Path) -> tuple[bool, str]:
    """
    Convert ``path`` to PNG using OpenCV.

    Args:
        path: Source image path.
        output_path: Destination ``.png`` path.

    Returns:
        ``(success, message)``.
    """
    img: Any = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return False, f"cv2 could not decode {path.name}"
    final_img: Any = _composite_alpha_cv2(img)
    ok: bool = bool(cv2.imwrite(str(output_path), final_img))
    return ok, "cv2" if ok else f"cv2 failed to write {output_path.name}"


def _convert_skimage(path: Path, output_path: Path) -> tuple[bool, str]:
    """
    Convert ``path`` to PNG using scikit-image.

    Args:
        path: Source image path.
        output_path: Destination ``.png`` path.

    Returns:
        ``(success, message)``.
    """
    img: Any = skio.imread(str(path))
    if img is None:
        return False, f"skimage could not decode {path.name}"
    if img.ndim == 3 and img.shape[2] == 4:
        rgb = img[:, :, :3].astype(float)
        alpha = img[:, :, 3:4].astype(float) / 255.0
        white = np.full_like(rgb, 255.0)
        img = (rgb * alpha + white * (1 - alpha)).astype(np.uint8)
    skio.imsave(str(output_path), img)
    return True, "skimage"


def _convert_pillow(path: Path, output_path: Path) -> tuple[bool, str]:
    """
    Convert ``path`` to PNG using Pillow.

    Args:
        path: Source image path.
        output_path: Destination ``.png`` path.

    Returns:
        ``(success, message)``.
    """
    with Image.open(path) as img:
        if img.mode in {"RGBA", "LA"}:
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            final_img = background
        elif img.mode != "RGB":
            final_img = img.convert("RGB")
        else:
            final_img = img
        final_img.save(output_path, "PNG")
    return True, "pillow"


def _convert_with_backends(path: Path, output_path: Path) -> tuple[bool, str]:
    """
    Try cv2, then skimage, then Pillow (in that order) until one succeeds.

    Args:
        path: Source image path.
        output_path: Destination ``.png`` path.

    Returns:
        ``(success, message)`` where ``message`` names the winning backend
        or concatenates failure reasons.
    """
    errors: list[str] = []

    if _CV2_AVAILABLE:
        ok, msg = _convert_cv2(path, output_path)
        if ok:
            return True, f"cv2 ({msg})"
        errors.append(msg)

    if _SKIMAGE_AVAILABLE:
        ok, msg = _convert_skimage(path, output_path)
        if ok:
            return True, f"skimage"
        errors.append(msg)

    if _PIL_AVAILABLE:
        ok, msg = _convert_pillow(path, output_path)
        if ok:
            return True, f"pillow"
        errors.append(msg)

    if not errors:
        errors.append("no image backend available")
    return False, "; ".join(errors)


# --- Public pipeline ------------------------------------------------------------


def convert_file(path: Path) -> ConvertResult:
    """
    Convert a single image file to PNG, replacing the original on success.

    Args:
        path: Path to the source image.

    Returns:
        ``(path, success, message)``. ``success`` is ``True`` only if the file
        was rewritten as ``.png`` and the original was deleted.
    """
    if not path.is_file() or path.suffix.lower() not in IMGEXT:
        return path, False, f"Skipping: {path.name} (Unsupported format or not a file)"

    output_path: Path = path.with_suffix(".png")
    if output_path.exists():
        return path, False, f"Skipping: {output_path.name} already exists"

    try:
        success, message = _convert_with_backends(path, output_path)
    except Exception as exc:
        return path, False, f"Error converting '{path.name}': {exc}"

    if not success:
        return path, False, f"Failed '{path.name}': {message}"

    try:
        path.unlink()
    except OSError as exc:
        return (
            path,
            False,
            f"Wrote {output_path.name} but could not delete source: {exc}",
        )

    return path, True, f"Converted '{path.name}' to '{output_path.name}' via {message}"


def gather_images(root: Path) -> list[Path]:
    """
    Recursively find image files under ``root``, skipping :data:`IGNORED_DIRS`.

    Args:
        root: Directory to search.

    Returns:
        A sorted list of image file paths.
    """
    files: list[Path] = []
    for f in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in f.parts):
            continue
        if f.is_file() and is_image(f):
            files.append(f)
    return sorted(files)


def main() -> None:
    """Entry point: find images, convert in parallel, report size delta."""
    start_size: int = gsz(".")
    files: list[Path] = gather_images(Path())

    if not files:
        print("No image files detected.")
        return

    print(f"Converting {len(files)} files...")

    changed_count: int = 0
    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[ConvertResult]] = [
            pool.apply_async(convert_file, (f,)) for f in files
        ]
        for async_res in async_results:
            try:
                _path, ok, message = async_res.get()
            except Exception as exc:
                logger.error(f"Worker raised: {exc}")
                continue
            if ok:
                changed_count += 1
                print(f"✓ {message}")
            else:
                logger.warning(f"✗ {message}")

    print(f"Done. {changed_count} files modified.")

    delta: int = gsz(".") - start_size
    if delta < 0:
        print(f"size reduced: - {fsz(delta)}")
    else:
        print(f"size increased: + {fsz(delta)}")


if __name__ == "__main__":
    raise SystemExit(main())
