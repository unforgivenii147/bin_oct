#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import fsz, get_files, gsz, mpf3
from PIL import Image
from PIL.Image import Image

try:
    import cv2

    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    try:
        from skimage import color, filters, io
        from skimage.util import img_as_ubyte

        HAS_SKIMAGE = True
    except ImportError:
        print("Error: Neither OpenCV nor scikit-image is available.")
        print(
            "Install one of them: pip install opencv-python or pip install scikit-image"
        )
        sys.exit(1)
MAX_QUEUE = 16


def process_image_cv2(image_path: Path) -> Image:
    img = cv2.imread(str(image_path))
    if img is None:
        print(f"Error: Could not load image from {image_path}")
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    gaussian_blur = cv2.GaussianBlur(blurred, (0, 0), 3)
    sharpened = cv2.addWeighted(blurred, 1.5, gaussian_blur, -0.5, 0)
    binary = cv2.adaptiveThreshold(
        sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    enhanced_img_pil = Image.fromarray(binary)
    enhanced = image_path.with_stem(image_path.stem + "_enhanced_pil")
    cv2.imwrite(str(enhanced), binary)
    return enhanced_img_pil


def process_image_skimage(image_path: Path) -> Image:
    try:
        img = io.imread(str(image_path))
    except Exception as e:
        print(f"Error: Could not load image from {image_path}: {e}")
        return None
    if len(img.shape) == 3:
        gray = color.rgb2gray(img)
    else:
        gray = img
    blurred = filters.gaussian(gray, sigma=5 / 3)
    gaussian_blur = filters.gaussian(blurred, sigma=3 / 3)
    sharpened = 1.5 * blurred - 0.5 * gaussian_blur
    sharpened = np.clip(sharpened, 0, 1)
    from skimage.filters import threshold_local

    binary = sharpened > threshold_local(sharpened, 11, "gaussian")
    binary_uint8 = img_as_ubyte(binary)
    enhanced_img_pil = Image.fromarray(binary_uint8)
    enhanced = image_path.with_stem(image_path.stem + "_enhanced_pil")
    io.imsave(str(enhanced), binary_uint8)
    return enhanced_img_pil


def process_file(image_path: Path) -> Image:
    if HAS_CV2:
        return process_image_cv2(image_path)
    else:
        return process_image_skimage(image_path)


def process_file2(image_path):
    if HAS_CV2:
        img = cv2.imread(str(image_path))
        if img is None:
            print(f"Error: Could not load image from {image_path}")
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        gaussian_blur = cv2.GaussianBlur(blurred, (0, 0), 3)
        sharpened = cv2.addWeighted(blurred, 1.5, gaussian_blur, -0.5, 0)
        binary = cv2.adaptiveThreshold(
            sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        enhanced = image_path.with_stem(image_path.stem + "_enhanced_cv")
        cv2.imwrite(str(enhanced), binary)
        return binary
    else:
        import numpy as np

        try:
            img = io.imread(str(image_path))
        except Exception as e:
            print(f"Error: Could not load image from {image_path}: {e}")
            return None
        if len(img.shape) == 3:
            gray = color.rgb2gray(img)
        else:
            gray = img
        blurred = filters.gaussian(gray, sigma=5 / 3)
        gaussian_blur = filters.gaussian(blurred, sigma=1.0)
        sharpened = 1.5 * blurred - 0.5 * gaussian_blur
        sharpened = np.clip(sharpened, 0, 1)
        from skimage.filters import threshold_local

        binary = sharpened > threshold_local(sharpened, 11, "gaussian")
        binary_uint8 = img_as_ubyte(binary)
        enhanced = image_path.with_stem(image_path.stem + "_enhanced_cv")
        io.imsave(str(enhanced), binary_uint8)
        return binary_uint8


def main() -> None:
    print(f"Using {('OpenCV' if HAS_CV2 else 'scikit-image')} for image processing")
    cwd = Path.cwd()
    before = gsz(cwd)
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_files(cwd, ext=[".png", ".jpg"])
    if not files:
        print("No image files found to process")
        sys.exit(0)
    if len(files) == 1:
        process_file(files[0])
        sys.exit(0)
    mpf3(process_file, files)
    mpf3(process_file2, files)
    diff_size = before - gsz(cwd)
    print(f"space saved : {fsz(diff_size)}")


if __name__ == "__main__":
    raise SystemExit(main())
