#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re

from weasyprint import HTML

INPUT_FILE = "dictionary.txt"
OUTPUT_FILE = "dictionary.pdf"
CUSTOM_FONT = "custom.ttf"


def convert_entry_to_html(raw_line: str) -> str | None:
    try:
        word, html_body = raw_line.strip().split("\t", 1)
    except ValueError:
        return None
    html_body = html_body.replace("<br />", "<br>")
    html_body = re.sub(r"</?[CFINEË]+[^>]*>", "", html_body)
    html_body = re.sub(r"<x [^>]*>", "<span>", html_body)
    html_body = html_body.replace("</x>", "</span>")
    html_body = re.sub(r'<Ë M="[^"]+" ?/?>', "", html_body)
    return f"""
    <html>
    <body>
        <div class="entry">
            <h1 class="word">{word}</h1>
            <div class="definition">{html_body}</div>
        </div>
    </body>
    </html>
    """


def main() -> None:
    with open(INPUT_FILE, encoding="utf-8") as f:
        lines = f.readlines()
    pages = []
    for line in lines:
        html = convert_entry_to_html(line)
        if html:
            pages.append(html)
    full_html = f"""
    <html>
        <head>
            <style>
                @font-face {{
                    font-family: "CustomFont";
                    src: url('{CUSTOM_FONT}');
                }}
                body {{
                    font-family: "CustomFont", sans-serif;
                    font-size: 16px;
                }}
                .entry {{
                    page-break-after: always;
                    padding: 30px;
                }}
                .word {{
                    margin-top: 0;
                    color:
                }}
                .definition {{
                    margin-top: 10px;
                    line-height: 1.5;
                }}
            </style>
        </head>
        <body>
    """
    for p in pages:
        full_html += p
    full_html += "</body></html>"
    HTML(string=full_html).write_pdf(OUTPUT_FILE)
    print("PDF created:", OUTPUT_FILE)


if __name__ == "__main__":
    raise SystemExit(main())
