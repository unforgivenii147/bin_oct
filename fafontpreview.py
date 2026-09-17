#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

from dh import FONTEXT

FONTEXTENSIONS = tuple(FONTEXT)
OUTPUT_HTML = "fa_fonts_preview.html"
FONT_SIZES = [14, 22]


def find_fonts(cwd: Path = Path.cwd()):
    fonts = []
    for dirpath, _, filenames in cwd.walk():
        fonts.extend(
            Path(dirpath) / filename
            for filename in filenames
            if filename.lower().endswith(FONTEXTENSIONS)
        )
    return fonts


def generate_html(font_files) -> str:
    html = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='UTF-8'>",
        "<title>Font Preview</title>",
        "<link rel=stylesheet src='/sdcard/_static/font_css/fontello.css'></link></head>",
        "<body>",
        "<h1>Font Preview</h1>",
    ]
    for font_path in font_files:
        font_name = Path(font_path).name
        html.extend(
            (
                "<div class='font-preview'>",
                "<style>",
                f"@font-face {{ font-family: '{font_name}'; src: url('{font_path}'); }}",
                "</style>",
            )
        )
        html.extend(
            f"<h1 style='font-family: \"{font_name}\"; font-size: {size}px;'>هنر برتز از گوهر آمد پدید</h1>"
            for size in FONT_SIZES
        )
        html.append(
            f"<div style='font-family: \"{font_name}\"; font-size: 12px;'>{font_name}</div><hr>"
        )
        html.append("</div>")
    html.append("</body></html>")
    return "\n".join(html)


def main() -> None:
    fonts = find_fonts()
    if not fonts:
        return
    html_content = generate_html(fonts)
    Path(OUTPUT_HTML).write_text(html_content, encoding="utf-8")
    print("font-preview.html created.")


if __name__ == "__main__":
    raise SystemExit(main())
