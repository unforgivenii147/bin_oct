#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys

from markdown2 import markdown_path
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from weasyprint import CSS, HTML


class ValidationError(Exception):
    pass


TOC_HTML = """
<nav class="toc">
<h1>Contents</h1>
<ul></ul>
</nav>
"""


def pygments_highlight(html: str) -> str:
    formatter = HtmlFormatter(cssclass="highlight")
    code_block_re = re.compile(
        r'<pre><code class="language-(\w+)">(.*?)</code></pre>', re.DOTALL
    )

    def repl(match) -> str:
        lang = match.group(1)
        code = match.group(2)
        code = code.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        try:
            lexer = get_lexer_by_name(lang)
        except Exception:
            lexer = TextLexer()
        return highlight(code, lexer, formatter)

    return code_block_re.sub(repl, html)


def md2pdf(pdf_path, md_path, css_path=None, base_url=None) -> None:
    extras = ["header-ids", "fenced-code-blocks", "tables", "cuddled-lists"]
    html = markdown_path(md_path, extras=extras)
    if not html.strip():
        raise ValidationError(msg)
    html = pygments_highlight(html)
    html = TOC_HTML + html
    html_doc = HTML(string=html, base_url=base_url)
    stylesheets = []
    if css_path:
        stylesheets.append(CSS(filename=css_path))
    html_doc.write_pdf(pdf_path, stylesheets=stylesheets)


if __name__ == "__main__":
    md_file = sys.argv[1]
    pdf_file = md_file.replace(".md", ".pdf")
    md2pdf(
        pdf_path=pdf_file,
        md_path=md_file,
        css_path="/sdcard/_static/css/book.css",
        base_url=".",
    )
