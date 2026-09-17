#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import cpu_count
from pathlib import Path

import pytesseract
from PIL import Image

TESSDATA_DIRS = [
    Path.home() / ".local" / "share" / "tessdata_best",
    Path.home() / ".local" / "share" / "tessdata_fast",
]
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp", ".gif"}


def get_images(path: str | Path | None = None) -> list[Path]:
    path = Path(path or Path.cwd())
    return (
        sorted(path.rglob("*")) if path.is_dir() else [path] if path.is_file() else []
    )


def extract_text(image_path: Path, tessdata_dir: Path) -> dict:
    if image_path.suffix.lower() not in IMAGE_EXTS:
        return None
    try:
        img = Image.open(image_path)
        config = f"--tessdata-dir {tessdata_dir} -l eng"
        text = pytesseract.image_to_string(img, config=config)
        return {
            "file": image_path.name,
            "tessdata": tessdata_dir.name,
            "text": text.strip(),
            "status": "success",
        }
    except Exception as e:
        return {
            "file": image_path.name,
            "tessdata": tessdata_dir.name,
            "text": "",
            "status": f"error: {e}",
        }


def process_image(args):
    image_path, tessdata_dir = args
    return extract_text(image_path, tessdata_dir)


def main() -> None:
    args = sys.argv[1:]
    paths = [Path(p) for p in args] if args else [Path.cwd()]
    images = []
    for path in paths:
        if path.is_dir():
            images.extend(
                [
                    f
                    for f in path.rglob("*")
                    if f.is_file() and f.suffix.lower() in IMAGE_EXTS
                ]
            )
        elif path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            images.append(path)
    if not images:
        print("No images found", file=sys.stderr)
        sys.exit(1)
    tasks = [(img, td) for img in images for td in TESSDATA_DIRS]
    with ProcessPoolExecutor(max_workers=cpu_count()) as executor:
        results = executor.map(process_image, tasks)
    for result in results:
        if result:
            print(f"\n{'=' * 40}")
            print(f"File: {result['file']}")
            print(f"Tessdata: {result['tessdata']}")
            print(f"Status: {result['status']}")
            if result["text"]:
                print(f"Text:\n{result['text']}")


if __name__ == "__main__":
    raise SystemExit(main())
