#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys

from markdown2 import markdown, markdown_path
from weasyprint import CSS, HTML


def md2pdf(
    pdf_path,
    md_content=None,
    md_path=None,
    css_path: str = "/sdcard/_static/css/markdown.css",
    base_url=None,
) -> None:
    raw_html = ""
    extras = ["cuddled-lists", "tables"]
    if md_path:
        raw_html = markdown_path(md_path, extras=extras)
    elif md_content:
        raw_html = markdown(md_content, extras=extras)
    if not len(raw_html):
        msg = "Input markdown seems empty"
        raise ValidationError(msg)
    html = HTML(string=raw_html, base_url=base_url)
    css = []
    if css_path:
        css.append(CSS(filename=css_path))
    html.write_pdf(pdf_path, stylesheets=css)


if __name__ == "__main__":
    md_file = sys.argv[1]
    pdf_file = md_file.replace(".md", ".pdf")
    md2pdf(pdf_path=pdf_file, md_path=md_file)
