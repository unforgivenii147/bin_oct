#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from bs4.element import AttributeValueList

cwd = Path.cwd()
INPUT_DIR = cwd
OUTPUT_DIR = cwd / "output"
ASSETS_DIR = cwd / "output" / "assets"
DOWNLOAD_REMOTE = False
TIMEOUT = 10
ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def save_asset(content: bytes, mime_type: str, file_hint="asset") -> Path:
    ext = mimetypes.guess_extension(mime_type) or ""
    counter = 0
    while True:
        fname = f"{file_hint}_{counter}{ext}"
        path = ASSETS_DIR / fname
        if not path.exists():
            break
        counter += 1
    path.write_bytes(content)
    return path


def extract_base64_data(
    data_url: AttributeValueList | str | None, file_hint: str = "asset"
) -> Path | None:
    m = re.match(r"data:(.*?);base64,(.*)", data_url, re.DOTALL)
    if not m:
        return None
    mime_type, encoded = m.groups()
    content = base64.b64decode(encoded)
    return save_asset(content, mime_type, file_hint)


def download_external_url(
    url: AttributeValueList | str | None, file_hint: str = "remote"
) -> Path | None:
    try:
        print("Downloading:", url)
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        mime = r.headers.get("Content-Type", "application/octet-stream")
        return save_asset(r.content, mime.split(";")[0], file_hint)
    except Exception:
        return None


def process_file(path: Path) -> None:
    path = Path(path)
    html = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    file_prefix = path.stem
    for i, style_tag in enumerate(soup.find_all("style")):
        if not style_tag.string:
            continue
        css = style_tag.string
        path = save_asset(css.encode("utf-8"), "text/css", f"{file_prefix}_style{i}")
        style_tag.replace_with(
            f'<link rel="stylesheet" href="{path.relative_to(OUTPUT_DIR)}">'
        )
    for i, script in enumerate(soup.find_all("script")):
        if script.get("src"):
            src = script.get("src")
            if src.startswith("http") and DOWNLOAD_REMOTE:
                path = download_external_url(src, f"{file_prefix}_script_remote")
                if path:
                    script["src"] = str(path.relative_to(OUTPUT_DIR))
            continue
        js = script.string or ""
        path = save_asset(
            js.encode("utf-8"), "application/javascript", f"{file_prefix}_script{i}"
        )
        script.replace_with(f'<script src="{path.relative_to(OUTPUT_DIR)}"></script>')
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src.startswith("data:"):
            path = extract_base64_data(src, f"{file_prefix}_img")
            if path:
                img["src"] = str(path.relative_to(OUTPUT_DIR))
        elif src.startswith("http") and DOWNLOAD_REMOTE:
            path = download_external_url(src, f"{file_prefix}_img_remote")
            if path:
                img["src"] = str(path.relative_to(OUTPUT_DIR))
    bg_re = re.compile(r'url\("(data:.*?)"\)')
    for tag in soup.find_all(style=True):
        style = tag["style"]
        m = bg_re.search(style)
        if m:
            data_url = m.group(1)
            path = extract_base64_data(data_url, f"{file_prefix}_bg")
            if path:
                tag["style"] = style.replace(
                    data_url, str(path.relative_to(OUTPUT_DIR))
                )
    for i, svg in enumerate(soup.find_all("svg")):
        svg_str = str(svg)
        path = save_asset(
            svg_str.encode("utf-8"), "image/svg+xml", f"{file_prefix}_svg{i}"
        )
        new_tag = soup.new_tag("img")
        new_tag["src"] = str(path.relative_to(OUTPUT_DIR))
        svg.replace_with(new_tag)
    for style in soup.find_all("style"):
        if not style.string:
            continue
        new_css = style.string
        fonts = re.findall(r'url\("(data:font\/.+?)"\)', new_css)
        for f in fonts:
            path = extract_base64_data(f, f"{file_prefix}_font")
            if path:
                new_css = new_css.replace(f, str(path.relative_to(OUTPUT_DIR)))
        style.string.replace_with(new_css)
    for link in soup.find_all("link", href=True):
        href = link["href"]
        if href.startswith("http") and DOWNLOAD_REMOTE:
            path = download_external_url(href, f"{file_prefix}_css_remote")
            if path:
                link["href"] = str(path)
    output_html_path = OUTPUT_DIR / path.relative_to(INPUT_DIR)
    output_html_path.parent.mkdir(parents=True, exist_ok=True)
    output_html_path.write_text(str(soup), encoding="utf-8")
    print("Processed:", path)


if __name__ == "__main__":
    for path in cwd.rglob("*"):
        if path.suffix.lower() in {".html", ".htm"} and "output" not in path.parts:
            process_file(path)
    print("\nAll done — extracted assets saved to ./output/")
