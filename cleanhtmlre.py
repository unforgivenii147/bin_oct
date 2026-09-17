#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path


def strip_html_comments(html: str) -> str:
    return re.sub(r"<!--(?!\[if).*?-->", "", html, flags=re.DOTALL)


def strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def strip_js_comments(js: str) -> str:
    result = []
    i = 0
    n = len(js)
    in_string = None
    in_line_comment = False
    in_block_comment = False
    in_regex = False

    def prev_non_space_char(buf):
        for ch in reversed(buf):
            if not ch.isspace():
                return ch
        return ""

    while i < n:
        c = js[i]
        nxt = js[i + 1] if i + 1 < n else ""
        if in_line_comment:
            if c == "\n":
                in_line_comment = False
                result.append(c)
            i += 1
            continue
        if in_block_comment:
            if c == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue
        if in_string:
            result.append(c)
            if c == "\\" and i + 1 < n:
                result.append(nxt)
                i += 2
                continue
            if c == in_string:
                in_string = None
            i += 1
            continue
        if in_regex:
            result.append(c)
            if c == "\\" and i + 1 < n:
                result.append(nxt)
                i += 2
                continue
            if c == "/":
                in_regex = False
            i += 1
            continue
        if c == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if c == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if c in ("'", '"', "`"):
            in_string = c
            result.append(c)
            i += 1
            continue
        if c == "/":
            prev_char = prev_non_space_char("".join(result))
            if prev_char in (
                "",
                "(",
                ",",
                "=",
                ":",
                "[",
                "!",
                "&",
                "|",
                "?",
                "{",
                ";",
                "+",
                "-",
                "*",
                "%",
                "<",
                ">",
                "\n",
                "return",
            ):
                in_regex = True
                result.append(c)
                i += 1
                continue
        result.append(c)
        i += 1
    return "".join(result)


def load_asset(src: str, base_dir: Path) -> str | None:
    try:
        if src.startswith(("http://", "https://")):
            with urllib.request.urlopen(src, timeout=10) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        if src.startswith("//"):
            url = "https:" + src
            with urllib.request.urlopen(url, timeout=10) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        if src.startswith("data:"):
            return None
        local_path = (base_dir / src.lstrip("/")).resolve()
        if local_path.is_file():
            return local_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"[warn] could not load asset '{src}': {e}", file=sys.stderr)
    return None


LINK_CSS_RE = re.compile(
    r'<link\b[^>]*rel=["\']stylesheet["\'][^>]*>',
    re.IGNORECASE,
)
HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
SCRIPT_SRC_RE = re.compile(
    r'<script\b([^>]*)\bsrc=["\']([^"\']+)["\']([^>]*)>\s*</script>',
    re.IGNORECASE,
)
STYLE_TAG_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.IGNORECASE | re.DOTALL)
SCRIPT_TAG_RE = re.compile(
    r"<script\b(?![^>]*\bsrc=)([^>]*)>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


def inline_css_links(html: str, base_dir: Path) -> str:
    def replace(match: re.Match) -> str:
        tag = match.group(0)
        href_match = HREF_RE.search(tag)
        if not href_match:
            return tag
        href = href_match.group(1)
        content = load_asset(href, base_dir)
        if content is None:
            return tag
        content = strip_css_comments(content)
        return f"<style>{content}</style>"

    return LINK_CSS_RE.sub(replace, html)


def inline_js_scripts(html: str, base_dir: Path) -> str:
    def replace(match: re.Match) -> str:
        pre_attrs, src, post_attrs = match.groups()
        content = load_asset(src, base_dir)
        if content is None:
            return match.group(0)
        content = strip_js_comments(content)
        attrs = pre_attrs + post_attrs
        attrs = re.sub(r'\ssrc=["\'][^"\']+["\']', "", attrs, flags=re.IGNORECASE)
        return f"<script{attrs}>{content}</script>"

    return SCRIPT_SRC_RE.sub(replace, html)


def clean_inline_style_blocks(html: str) -> str:
    def replace(match: re.Match) -> str:
        css = match.group(1)
        cleaned = strip_css_comments(css)
        full_tag_open = match.group(0).split(">", 1)[0] + ">"
        return f"{full_tag_open}{cleaned}</style>"

    return STYLE_TAG_RE.sub(replace, html)


def clean_inline_script_blocks(html: str) -> str:
    def replace(match: re.Match) -> str:
        attrs, js = match.groups()
        cleaned = strip_js_comments(js)
        return f"<script{attrs}>{cleaned}</script>"

    return SCRIPT_TAG_RE.sub(replace, html)


def clean_html_file(input_path: Path) -> Path:
    base_dir = input_path.parent
    html = input_path.read_text(encoding="utf-8", errors="replace")
    html = inline_css_links(html, base_dir)
    html = inline_js_scripts(html, base_dir)
    html = clean_inline_style_blocks(html)
    html = clean_inline_script_blocks(html)
    html = strip_html_comments(html)
    html = re.sub(r"\n\s*\n+", "\n\n", html)
    out_path = input_path.with_name(f"{input_path.stem}_cleaned.html")
    out_path.write_text(html, encoding="utf-8")
    return out_path


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python clean_html.py <input.html>", file=sys.stderr)
        sys.exit(1)
    input_path = Path(sys.argv[1]).expanduser().resolve()
    if not input_path.is_file():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    out_path = clean_html_file(input_path)
    print(f"Cleaned file written to: {out_path}")


if __name__ == "__main__":
    main()
