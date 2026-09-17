#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
from io import BytesIO
from pathlib import Path

import pycurl
import requests
from bs4 import BeautifulSoup
from bs4.element import AttributeValueList

cwd = Path.cwd()
OUTPUT_DIR = cwd / "output"
ASSETS_DIR = cwd / "output" / "assets"
DOWNLOAD_REMOTE = True
TIMEOUT = 10
if not OUTPUT_DIR.exists():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
if not ASSETS_DIR.exists():
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
HASH_MAP = {}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_hashed_asset(content: bytes, mime_type: str):
    digest = sha256(content)
    if digest in HASH_MAP:
        return HASH_MAP[digest]
    ext = mimetypes.guess_extension(mime_type) or ""
    fname = f"{digest}{ext}"
    path = ASSETS_DIR / fname
    path.write_bytes(content)
    HASH_MAP[digest] = path
    return path


def extract_base64(data_url: AttributeValueList | str | None):
    m = re.match(r"data:(.*?);base64,(.*)", data_url, re.DOTALL)
    if not m:
        return None
    mime_type, encoded = m.groups()
    content = base64.b64decode(encoded)
    return save_hashed_asset(content, mime_type)


def download_external(url: str):
    if not isinstance(url, str):
        return None
    buffer = BytesIO()
    headers_buffer = BytesIO()
    c = pycurl.Curl()
    try:
        c.setopt(c.URL, url)
        c.setopt(c.WRITEDATA, buffer)
        c.setopt(c.HEADERDATA, headers_buffer)
        c.setopt(c.TIMEOUT, TIMEOUT)
        c.setopt(c.FOLLOWLOCATION, True)
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "Anonymously/1.0 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        c.setopt(c.USERAGENT, user_agent)
        c.setopt(c.SSL_VERIFYPEER, 1)
        c.setopt(c.SSL_VERIFYHOST, 2)
        c.perform()
        status_code = c.getinfo(c.RESPONSE_CODE)
        if status_code != 200:
            c.close()
            return None
        raw_headers = headers_buffer.getvalue().decode("iso-8859-1").lower()
        mime = "application/octet-stream"
        for line in raw_headers.split("\r\n"):
            if line.startswith("content-type:"):
                mime = line.split(":", 1)[1].strip()
                break
        content = buffer.getvalue()
        c.close()
        return save_hashed_asset(content, mime.split(";")[0])
    except Exception:
        c.close()
        return None


def download_external_with_requests(url: AttributeValueList | str):
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        mime = r.headers.get("Content-Type", "application/octet-stream")
        return save_hashed_asset(r.content, mime.split(";")[0])
    except Exception:
        return None


processed_html_files = []


def process_html(path: Path) -> None:
    html = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    processed_html_files.append(soup)
    for style in soup.find_all("style"):
        if not style.string:
            continue
        css = style.string.encode("utf-8")
        path = save_hashed_asset(css, "text/css")
        style.replace_with(
            f'<link rel="stylesheet" href="{path.relative_to(OUTPUT_DIR)}">'
        )
    for script in soup.find_all("script"):
        if script.get("src"):
            src = script["src"]
            if src.startswith("http") and DOWNLOAD_REMOTE:
                path = download_external(src)
                if path:
                    script["src"] = str(path.relative_to(OUTPUT_DIR))
            continue
        js = (script.string or "").encode("utf-8")
        path = save_hashed_asset(js, "application/javascript")
        script.replace_with(f'<script src="{path.relative_to(OUTPUT_DIR)}"></script>')
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src.startswith("data:"):
            path = extract_base64(src)
            if path:
                img["src"] = str(path.relative_to(OUTPUT_DIR))
    bg_re = re.compile(r'url\("(data:.*?)"\)')
    for tag in soup.find_all(style=True):
        m = bg_re.search(tag["style"])
        if m:
            data_url = m.group(1)
            path = extract_base64(data_url)
            if path:
                tag["style"] = tag["style"].replace(
                    data_url, str(path.relative_to(OUTPUT_DIR))
                )
    for svg in soup.find_all("svg"):
        svg_bytes = str(svg).encode("utf-8")
        path = save_hashed_asset(svg_bytes, "image/svg+xml")
        new_tag = soup.new_tag("img")
        new_tag["src"] = str(path.relative_to(OUTPUT_DIR))
        svg.replace_with(new_tag)
    for link in soup.find_all("link", href=True):
        href = link["href"]
        if href.startswith("http") and DOWNLOAD_REMOTE:
            print(href)
    out_path = OUTPUT_DIR / path.relative_to(cwd)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(str(soup), encoding="utf-8")
    print("Processed:", path)


def build_single_page() -> None:
    merged = BeautifulSoup("<html><head></head><body></body></html>", "html.parser")
    body = merged.body
    for soup in processed_html_files:
        if soup.body:
            for el in soup.body.contents:
                body.append(el)
    for asset_file in ASSETS_DIR.iterdir():
        mime = mimetypes.guess_type(asset_file.name)[0] or "application/octet-stream"
        data = asset_file.read_bytes()
        encoded = base64.b64encode(data).decode()
        data_url = f"data:{mime};base64,{encoded}"
        merged_str = str(merged)
        merged_str = merged_str.replace(
            str(asset_file.relative_to(OUTPUT_DIR)), data_url
        )
        merged = BeautifulSoup(merged_str, "html.parser")
    for link in merged.find_all("link", rel="stylesheet"):
        href = link.get("href", "")
        if href.startswith("data:"):
            css_data = re.sub(r"^data:.*?;base64,", "", href)
            decoded = base64.b64decode(css_data).decode("utf-8", errors="ignore")
            style_tag = merged.new_tag("style")
            style_tag.string = decoded
            link.replace_with(style_tag)
    for script in merged.find_all("script", src=True):
        src = script["src"]
        if src.startswith("data:"):
            js_data = re.sub(r"^data:.*?;base64,", "", src)
            decoded = base64.b64decode(js_data).decode("utf-8", errors="ignore")
            new_script = merged.new_tag("script")
            new_script.string = decoded
            script.replace_with(new_script)
    out_file = OUTPUT_DIR / "single_page_local.html"
    out_file.write_text(str(merged), encoding="utf-8")
    print("\nCreated:", out_file)


if __name__ == "__main__":
    for path in cwd.rglob("*"):
        if path.suffix.lower() in {".html", ".htm"} and "output" not in path.parts:
            process_html(path)
    build_single_page()
    print("\nDONE — all assets extracted, deduped, hashed, and packed!")
