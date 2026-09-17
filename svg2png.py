#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import cairosvg
from dh import get_files, mpf3
from PIL import Image


def process_file(path) -> None:
    path = Path(path)
    png_file = path.with_suffix(".png")
    try:
        with path.open("rb") as image:
            imageBinary = BytesIO(image.read())
            buff = BytesIO()
            cairosvg.svg2png(bytestring=imageBinary.getvalue(), write_to=buff)
            buff.seek(0)
            img = Image.open(buff)
            img.save(png_file)
    except:
        pass


def main() -> None:
    cwd = Path.cwd()
    files = get_files(cwd, ext=[".svg"])
    mpf3(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
