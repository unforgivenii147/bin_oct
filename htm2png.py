#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import cairosvg
from weasyprint import HTML


def html_to_png_cairo(html_content, output_path, width=None):
    if html_content.startswith(("<", "<!DOCTYPE")):
        html = HTML(string=html_content)
    else:
        html = HTML(filename=html_content)
    pdf_bytes = html.write_pdf()
    cairosvg.svg2png(
        bytestring=pdf_bytes, write_to=output_path, output_width=width, scale=2.0
    )
    print(f"PNG saved to: {output_path}")
