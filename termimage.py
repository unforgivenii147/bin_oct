#!/data/data/com.termux/files/home/.local/bin/python
"""
A lightweight Python implementation of termimage.
Displays images directly in the terminal using ANSI escape codes.
"""

import argparse
import os
import sys
from pathlib import Path
from urllib.request import urlopen

# Supported extensions
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def is_image_file(path: Path) -> bool:
    """Check if a file path is a supported image based on extension."""
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS


def get_terminal_width() -> int:
    """Get current terminal width in columns."""
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def load_ppm(path: Path):
    """
    Minimal native reader for ASCII/Binary PPM (P3/P6) formats to avoid external dependencies.
    For production, installing 'Pillow' is recommended for full format support.
    """
    with path.open("rb") as f:
        header = []
        while len(header) < 4:
            line = f.readline().strip()
            if not line or line.startswith(b"#"):
                continue
            header.extend(line.split())

        fmt, width, height, max_val = (
            header[0],
            int(header[1]),
            int(header[2]),
            int(header[3]),
        )
        data = f.read()

    pixels = []
    if fmt == b"P6":  # Binary RGB
        for i in range(0, len(data), 3):
            if i + 2 < len(data):
                pixels.append((data[i], data[i + 1], data[i + 2]))
    elif fmt == b"P3":  # ASCII RGB
        numbers = [int(n) for n in data.split()]
        for i in range(0, len(numbers), 3):
            pixels.append((numbers[i], numbers[i + 1], numbers[i + 2]))

    return width, height, pixels


def render_half_blocks(
    width: int, height: int, pixels: list[tuple[int, int, int]], max_width: int
):
    """Render image pixels using half-block characters (2 vertical pixels per cell)."""
    # Downsample width to fit terminal
    scale = max(1, width // max_width)
    scaled_w = width // scale
    scaled_h = height // scale

    # Resample grid (nearest neighbor)
    grid = []
    for y in range(scaled_h):
        row = []
        for x in range(scaled_w):
            orig_x = min(x * scale, width - 1)
            orig_y = min(y * scale, height - 1)
            idx = orig_y * width + orig_x
            row.append(pixels[idx] if idx < len(pixels) else (0, 0, 0))
        grid.append(row)

    # Output using ANSI escape codes: \033[38;2;R;G;Bm (fg) and \033[48;2;R;G;Bm (bg)
    lines = []
    for y in range(0, scaled_h - 1, 2):
        row_str = []
        for x in range(scaled_w):
            top_r, top_g, top_b = grid[y][x]
            bot_r, bot_g, bot_b = grid[y + 1][x]
            # Top half block char ▀ uses fg color for top pixel, bg color for bottom pixel
            cell = f"\033[38;2;{top_r};{top_g};{top_b}m\033[48;2;{bot_r};{bot_g};{bot_b}m▀\033[0m"
            row_str.append(cell)
        lines.append("".join(row_str))

    return "\n".join(lines)


def render_file(path: Path, max_width: int):
    """Attempts to render an image file to stdout."""
    print(f"\n--- {path} ---")

    # Try Pillow if installed for universal format support
    try:
        from PIL import Image

        with Image.open(path) as img:
            img = img.convert("RGB")
            w, h = img.size
            pixels = list(img.getdata())
            print(render_half_blocks(w, h, pixels, max_width))
            return
    except ImportError:
        pass

    # Native PPM fallback if Pillow isn't available
    if path.suffix.lower() == ".ppm":
        try:
            w, h, pixels = load_ppm(path)
            print(render_half_blocks(w, h, pixels, max_width))
            return
        except Exception as e:
            print(f"Error reading PPM file {path}: {e}")
            return

    print(
        f"Unable to render '{path.name}'. "
        "Install 'Pillow' (`pip install pillow`) to view PNG/JPG/WebP/GIF formats."
    )


def traverse_directory(root_dir: Path) -> list[Path]:
    """Recursively discover image files using pathlib.Path.rglob()."""
    images = []
    # Path.rglob("*") traverses directory recursively
    for path in root_dir.rglob("*"):
        if is_image_file(path):
            images.append(path)
    return sorted(images)


def main():
    parser = argparse.ArgumentParser(
        description="Termimage in Python: Render images in your terminal."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Image files or directories to render. Defaults to current directory recursively if omitted.",
    )
    parser.add_argument(
        "-w",
        "--width",
        type=int,
        default=None,
        help="Target rendering width in terminal columns (defaults to auto terminal width).",
    )

    args = parser.parse_args()
    max_width = args.width or get_terminal_width()

    # Rule: If no CLI arguments provided, target current directory recursively
    if not args.paths:
        target_paths = [Path.cwd()]
    else:
        target_paths = args.paths

    # Discover target image files using pathlib
    target_images: list[Path] = []
    for path in target_paths:
        if path.is_dir():
            target_images.extend(traverse_directory(path))
        elif is_image_file(path):
            target_images.append(path)
        else:
            print(
                f"Warning: '{path}' is not a directory or supported image file.",
                file=sys.stderr,
            )

    if not target_images:
        print("No image files found.")
        sys.exit(0)

    # Render discovered images
    for img_path in target_images:
        render_file(img_path, max_width)


if __name__ == "__main__":
    main()
