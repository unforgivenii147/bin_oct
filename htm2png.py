#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path
import cairosvg
from weasyprint import HTML
import sys


def html_to_png(path, width=None):
    output_path = path.with_suffix(".png")
    html = HTML(filename=str(path))
    pdf_bytes = html.write_pdf()
    cairosvg.svg2png(
        bytestring=pdf_bytes, write_to=str(output_path), output_width=width, scale=2.0
    )
    print(f"PNG saved to: {output_path.name}")


def main() -> None:
    fn = Path(sys.argv[1].strip())
    html_to_png(fn)


if __name__ == "__main__":
    raise SystemExit(main())
