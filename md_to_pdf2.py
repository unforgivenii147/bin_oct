#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

import markdown
import weasyprint

CSS_TEMPLATE = """
/* ==========================================================================
   0. LOCAL FONTS CONFIGURATION
   ========================================================================== */
@font-face {
    font-family: "LocalInter";
    src: url("fonts/Inter-Regular.ttf");
    font-weight: normal;
    font-style: normal;
}
@font-face {
    font-family: "LocalInter";
    src: url("fonts/Inter-Bold.ttf");
    font-weight: bold;
    font-style: normal;
}
@font-face {
    font-family: "LocalMono";
    src: url("fonts/JetBrainsMono-Regular.ttf");
    font-weight: normal;
    font-style: normal;
}
/* ==========================================================================
   1. PAGE SETUP & PAGED MEDIA
   ========================================================================== */
@page {
    size: A4;
    margin: 20mm;
    @bottom-right {
        content: "Page " counter(page) " of " counter(pages);
        font-family: "LocalInter", sans-serif;
        font-size: 9pt;
        color:
    }
}
h1, h2, h3, h4, h5, h6 { page-break-after: avoid; break-after: avoid; }
blockquote, pre, table, figure { page-break-inside: avoid; break-inside: avoid; }
ul, ol { page-break-inside: auto; }
li { page-break-inside: avoid; break-inside: avoid; }
/* ==========================================================================
   2. TYPOGRAPHY & BASE STYLES
   ========================================================================== */
html, body {
    font-family: "LocalInter", sans-serif;
    font-size: 11pt;
    line-height: 1.6;
    color:
}
p {
    margin-top: 0;
    margin-bottom: 1.2em;
    text-align: justify;
}
h1 {
    font-size: 24pt;
    margin-top: 0;
    margin-bottom: 15pt;
    color:
    border-bottom: 2px solid
    padding-bottom: 5pt;
}
h2 {
    font-size: 18pt;
    margin-top: 24pt;
    margin-bottom: 12pt;
    color:
    border-bottom: 1px solid
    padding-bottom: 3pt;
}
h3 {
    font-size: 14pt;
    margin-top: 18pt;
    margin-bottom: 8pt;
    color:
}
/* ==========================================================================
   3. INLINE ELEMENTS & DECORATIONS
   ========================================================================== */
a { color:
a[href^="http"]:after {
    content: " (" attr(href) ")";
    font-size: 9pt;
    color:
}
strong { color:
code {
    font-family: "LocalMono", monospace;
    font-size: 9.5pt;
    background-color:
    padding: 2px 4px;
    border-radius: 3px;
    color:
}
blockquote {
    margin: 1.5em 0;
    padding: 0.5em 15px;
    border-left: 4px solid
    color:
    background-color:
    font-style: italic;
}
/* ==========================================================================
   4. CODE BLOCKS (Markdown ``` )
   ========================================================================== */
pre {
    background-color:
    border: 1px solid
    border-radius: 4px;
    padding: 12px;
    margin: 1.5em 0;
    overflow: hidden;
}
pre code {
    background-color: transparent;
    padding: 0;
    border-radius: 0;
    color:
    font-family: "LocalMono", monospace;
    font-size: 9pt;
    white-space: pre-wrap;
}
/* ==========================================================================
   5. TABLES & LISTS
   ========================================================================== */
table {
    width: 100%;
    border-collapse: collapse;
    margin: 20px 0;
    font-size: 10.5pt;
}
th, td {
    border: 1px solid
    padding: 8px 12px;
    text-align: left;
}
th {
    background-color:
    font-weight: bold;
    color:
}
tr:nth-child(even) { background-color:
ul, ol { margin-top: 0; margin-bottom: 1.5em; padding-left: 24px; }
li { margin-bottom: 0.4em; }
/* ==========================================================================
   6. IMAGES / FIGURES
   ========================================================================== */
img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 20px auto;
    border-radius: 4px;
}
"""


def convert_md_to_pdf(input_path_str: str):
    input_file = Path(input_path_str)
    if not input_file.exists():
        print(f"❌ Error: The file '{input_path_str}' does not exist.")
        sys.exit(1)
    output_pdf = input_file.with_suffix(".pdf")
    print(f"📖 Reading: {input_file.name}")
    md_content = input_file.read_text(encoding="utf-8")
    print("🛠️  Converting Markdown to HTML...")
    html_body = markdown.markdown(md_content, extensions=["extra", "codehilite"])
    full_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{input_file.stem}</title>
</head>
<body>
    {html_body}
</body>
</html>"""
    print("🚀 Compiling PDF with WeasyPrint using local fonts...")
    try:
        html_doc = weasyprint.HTML(string=full_html, base_url=str(input_file.parent))
        css_doc = weasyprint.CSS(string=CSS_TEMPLATE)
        html_doc.write_pdf(target=output_pdf, stylesheets=[css_doc])
        print(f"✅ Success! PDF generated at:\n   👉 {output_pdf.resolve()}")
    except Exception as e:
        print(f"❌ WeasyPrint Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ Usage Error: Provide an input Markdown file.")
        sys.exit(1)
    convert_md_to_pdf(sys.argv[1])
