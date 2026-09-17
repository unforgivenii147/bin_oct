#!/data/data/com.termux/files/home/.local/bin/python
"""Standalone HTML/CSS bundler: inline local images, CSS, JS, and non-image
remote assets (fonts, CSS, JS) as base64 data URIs into HTML files and
process standalone CSS files. Uses a fixed multiprocessing pool of 8 workers.
Logs via loguru, handles paths with pathlib, and is fully type-annotated.
"""

import argparse
import base64
import mimetypes
import re
import sys
import time
from multiprocessing import Pool
from pathlib import Path
from re import Match
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from loguru import logger

logger.remove()
logger.add(
    sys.stderr, level="WARNING", format="<red>{level}</red> | <cyan>{message}</cyan>"
)

IMAGE_EXTENSIONS: set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".avif",
    ".bmp",
    ".tiff",
}
CSS_URL_PATTERN: re.Pattern[str] = re.compile(r'url\((["\']?)([^)"\']+)\1\)')
TIMEOUT: int = 15
POOL_SIZE: int = 8


def is_remote(url: str) -> bool:
    """Return True if the URL is an absolute or protocol-relative remote URL."""
    return urlparse(url).scheme in ("http", "https") or url.startswith("//")


def is_image(url: str) -> bool:
    """Return True if the URL path has a known image file extension."""
    ext = Path(urlparse(url).path).suffix.lower()
    return ext in IMAGE_EXTENSIONS


def get_mime_type(path: str) -> str:
    """Guess the MIME type for a file path, with fallbacks for common fonts."""
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        ext = Path(path).suffix.lower()
        if ext == ".woff2":
            return "font/woff2"
        if ext == ".woff":
            return "font/woff"
        if ext == ".ttf":
            return "font/ttf"
        if ext == ".eot":
            return "application/vnd.ms-fontobject"
        return "application/octet-stream"
    return mime


def fetch_remote(url: str) -> bytes | None:
    """Fetch a remote URL and return its bytes, or None on failure."""
    if url.startswith("//"):
        url = "https:" + url
    try:
        with requests.get(url, timeout=TIMEOUT) as response:
            response.raise_for_status()
            return response.content
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None


def read_local(path: Path) -> bytes | None:
    """Read a local file and return its bytes, or None on failure."""
    try:
        return path.read_bytes()
    except Exception as e:
        logger.error(f"Failed to read {path}: {e}")
        return None


def process_css_content(
    css_content: str, base_path: Path, base_url: str | None = None
) -> tuple[str, int, int]:
    """Inline url(...) references in CSS as data URIs.

    Returns the transformed CSS and counts of embedded local and remote assets.
    """
    loc: int = 0
    rem: int = 0

    def replacer(match: Match[str]) -> str:
        nonlocal loc, rem
        quote: str = match.group(1)
        url: str = match.group(2)
        if url.startswith("data:"):
            return match.group(0)
        if is_remote(url):
            if is_image(url):
                return match.group(0)
            target_url: str = urljoin(base_url, url) if base_url else url
            content = fetch_remote(target_url)
            if content:
                mime: str = get_mime_type(urlparse(target_url).path)
                b64: str = base64.b64encode(content).decode("ascii")
                rem += 1
                return f"url({quote}data:{mime};base64,{b64}{quote})"
            return match.group(0)
        else:
            clean_url: str = url.split("?")[0].split("#")[0]
            local_file: Path = (base_path.parent / clean_url).resolve()
            if not local_file.exists():
                logger.warning(f"Missing local CSS asset referenced: {local_file}")
                return match.group(0)
            content = read_local(local_file)
            if content:
                mime = get_mime_type(str(local_file))
                b64 = base64.b64encode(content).decode("ascii")
                loc += 1
                return f"url({quote}data:{mime};base64,{b64}{quote})"
            return match.group(0)

    new_css: str = CSS_URL_PATTERN.sub(replacer, css_content)
    return new_css, loc, rem


def process_html_file(path: Path) -> dict[str, Any]:
    """Inline assets referenced by an HTML file and rewrite it in place."""
    stats: dict[str, Any] = {
        "path": str(path),
        "local": 0,
        "remote": 0,
        "time": 0.0,
        "status": "success",
    }
    start: float = time.perf_counter()
    try:
        html_text: str = path.read_text(encoding="utf-8")
        soup: BeautifulSoup = BeautifulSoup(html_text, "html.parser")

        img: Tag
        for img in soup.find_all("img"):
            src: str | None = img.get("src")
            if not src or src.startswith("data:"):
                continue
            if is_remote(src):
                continue
            clean_src: str = src.split("?")[0].split("#")[0]
            local_img_path: Path = (path.parent / clean_src).resolve()
            if local_img_path.exists():
                content = read_local(local_img_path)
                if content:
                    b64: str = base64.b64encode(content).decode("ascii")
                    mime: str = get_mime_type(str(local_img_path))
                    img["src"] = f"data:{mime};base64,{b64}"
                    stats["local"] += 1
            else:
                logger.warning(f"Missing local image: {local_img_path} in {path}")

        link: Tag
        for link in soup.find_all("link", rel="stylesheet"):
            href: str | None = link.get("href")
            if not href:
                continue
            css_text: str = ""
            base_url: str | None = None
            css_base_path: Path = path
            if is_remote(href):
                raw = fetch_remote(href)
                if raw:
                    css_text = raw.decode("utf-8", errors="ignore")
                    base_url = href
                    stats["remote"] += 1
            else:
                clean_href: str = href.split("?")[0].split("#")[0]
                local_css_path: Path = (path.parent / clean_href).resolve()
                if local_css_path.exists():
                    css_text = local_css_path.read_text(
                        encoding="utf-8", errors="ignore"
                    )
                    css_base_path = local_css_path
                    stats["local"] += 1
                else:
                    logger.warning(f"Missing local CSS: {local_css_path} in {path}")
            if css_text:
                processed_css, c_loc, c_rem = process_css_content(
                    css_text, css_base_path, base_url
                )
                stats["local"] += c_loc
                stats["remote"] += c_rem
                style_tag: Tag = soup.new_tag("style")
                style_tag.string = processed_css
                link.replace_with(style_tag)

        script: Tag
        for script in soup.find_all("script"):
            src = script.get("src")
            if not src:
                continue
            script_text: str = ""
            if is_remote(src):
                raw = fetch_remote(src)
                if raw:
                    script_text = raw.decode("utf-8", errors="ignore")
                    stats["remote"] += 1
            else:
                clean_src = src.split("?")[0].split("#")[0]
                local_script: Path = (path.parent / clean_src).resolve()
                if local_script.exists():
                    script_text = local_script.read_text(
                        encoding="utf-8", errors="ignore"
                    )
                    stats["local"] += 1
                else:
                    logger.warning(f"Missing local script: {local_script} in {path}")
            if script_text:
                new_script: Tag = soup.new_tag("script")
                new_script.string = script_text
                script.replace_with(new_script)

        tag: Tag
        for tag in soup.find_all(style=True):
            style_attr: str = tag["style"]
            processed, l, r = process_css_content(style_attr, path)
            tag["style"] = processed
            stats["local"] += l
            stats["remote"] += r

        style: Tag
        for style in soup.find_all("style"):
            if style.string:
                processed, l, r = process_css_content(style.string, path)
                style.string = processed
                stats["local"] += l
                stats["remote"] += r

        path.write_text(str(soup), encoding="utf-8")
    except Exception as e:
        stats["status"] = f"error: {e}"
        logger.error(f"Failed to process HTML file {path}: {e}")
    stats["time"] = time.perf_counter() - start
    return stats


def process_css_file(path: Path) -> dict[str, Any]:
    """Inline assets referenced by a standalone CSS file and rewrite it."""
    stats: dict[str, Any] = {
        "path": str(path),
        "local": 0,
        "remote": 0,
        "time": 0.0,
        "status": "success",
    }
    start: float = time.perf_counter()
    try:
        content: str = path.read_text(encoding="utf-8")
        processed_css, l, r = process_css_content(content, path)
        stats["local"] += l
        stats["remote"] += r
        path.write_text(processed_css, encoding="utf-8")
    except Exception as e:
        stats["status"] = f"error: {e}"
        logger.error(f"Failed to process CSS file {path}: {e}")
    stats["time"] = time.perf_counter() - start
    return stats


def process_file(path: Path) -> dict[str, Any]:
    """Dispatch a single file to the correct processor based on extension."""
    if path.suffix.lower() == ".html":
        return process_html_file(path)
    elif path.suffix.lower() == ".css":
        return process_css_file(path)
    return {
        "path": str(path),
        "local": 0,
        "remote": 0,
        "time": 0.0,
        "status": "skipped",
    }


def main() -> None:
    """Parse arguments, collect target files, and run the pool of workers."""
    parser = argparse.ArgumentParser(description="Standalone HTML/CSS Bundler Tool")
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to process (default: current directory)",
    )
    args = parser.parse_args()

    targets: list[Path] = []
    for p_str in args.paths:
        p = Path(p_str)
        if p.is_file() and p.suffix.lower() in (".html", ".css"):
            targets.append(p)
        elif p.is_dir():
            targets.extend(p.rglob("*.html"))
            targets.extend(p.rglob("*.css"))

    # Deduplicate while preserving resolved identity
    unique: dict[Path, Path] = {p.resolve(): p for p in targets}
    targets = list(unique.values())

    if not targets:
        logger.warning("No HTML or CSS files found to process.")
        return

    print(f"Processing {len(targets)} files with a pool of {POOL_SIZE} workers...")

    t_loc: int = 0
    t_rem: int = 0
    start_time: float = time.perf_counter()

    pool: Pool = Pool(processes=POOL_SIZE)
    try:
        async_results = [pool.apply_async(process_file, (p,)) for p in targets]
        for async_result in async_results:
            s: dict[str, Any] = async_result.get()
            raw_path = Path(s["path"])
            try:
                display_path: Path = raw_path.relative_to(Path.cwd())
            except ValueError:
                display_path = raw_path

            t_loc += s["local"]
            t_rem += s["remote"]
            status: str = s["status"]

            if status == "success":
                print(
                    f"[SUCCESS] {display_path} ({s['time']:.2f}s) - "
                    f"Embedded: {s['local']} local, {s['remote']} remote"
                )
            elif status == "skipped":
                pass
            else:
                logger.error(f"[ERROR] {display_path} - {status}")
    finally:
        pool.close()
        pool.join()

    total_time: float = time.perf_counter() - start_time
    logger.success(f"Build Complete in {total_time:.2f}s!")
    print(f"Total globally embedded resources: {t_loc} local, {t_rem} remote.")


if __name__ == "__main__":
    main()
