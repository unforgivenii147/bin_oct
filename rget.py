#!/data/data/com.termux/files/home/.local/bin/python
"""
Prompt: Write a Python script that reads URLs from a text file (default: urls.txt),
filters them by safe file extensions (fonts, css, js, archives, docs), and downloads
them concurrently using multiprocessing.Pool.apply_async with a fixed pool of 8
workers. Support HTTP range-based resumable downloads, retry on transient failures,
and HEAD requests for size checks. Store files under downloads/ using pathlib for
all path operations. Use loguru for logging with tqdm progress bars, and provide
full type hints and docstrings throughout.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from loguru import logger
from tqdm import tqdm

MAX_WORKERS: int = 8
MAX_RETRIES: int = 3
TIMEOUT: int = 60
OUTPUT_DIR: str = "downloads"
URLS_FILE: str = "urls.txt"

SAFE_EXTENSIONS: list[str] = [
    r"\.ttf$",
    r"\.woff$",
    r"\.woff2$",
    r"\.eot$",
    r"\.otf$",
    r"\.min\.css$",
    r"\.min\.js$",
    r"\.css$",
    r"\.js$",
    r"\.pdf$",
    r"\.html?$",
    r"\.whl$",
    r"\.tar\.(gz|xz|zst|bz2|lzma|7z)$",
    r"\.zip$",
]

EXT_PATTERN: re.Pattern[str] = re.compile(r"|".join(SAFE_EXTENSIONS), re.IGNORECASE)


def sanitize_filename(name: str) -> str:
    """Sanitize a filename by URL-decoding and replacing forbidden characters."""
    name = unquote(name)
    name = re.sub(r'[<>:"|?*]', "_", name)
    return name[:255].strip() or "downloaded_file"


def extract_filename(url: str) -> str:
    """Derive a safe local filename from a URL's path component."""
    parsed = urlparse(url)
    path = parsed.path
    filename = path.split("/")[-1] or "index.html"
    filename = filename.split("#")[0]
    filename = filename.split("?")[0]
    filename = sanitize_filename(filename)
    if not re.search(r"\.[a-zA-Z0-9]+$", filename):
        filename += ".dat"
    return filename


def is_safe_extension(url: str) -> bool:
    """Return True if the URL's basename matches one of the safe extensions."""
    parsed = urlparse(url)
    path = parsed.path
    filename = path.split("/")[-1]
    base_name = filename.split("?")[0].split("#")[0]
    return bool(EXT_PATTERN.search(base_name))


def get_filesize(url: str, session: requests.Session) -> int | None:
    """Return the remote Content-Length via HEAD, or None if unavailable."""
    try:
        r = session.head(url, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        size = r.headers.get("Content-Length")
        return int(size) if size else None
    except Exception:
        return None


def download_one(
    url: str,
    session: requests.Session,
    output_dir: str,
    resume_from: int | None = None,
) -> tuple[str, bool, str]:
    """Download a single URL with optional range-based resume.

    Returns a tuple of (url, success, message_or_path).
    """
    filename = extract_filename(url)
    path = Path(output_dir) / filename
    offset = 0

    if resume_from and path.exists():
        offset = path.stat().st_size
        remote_size = get_filesize(url, session)
        if remote_size is not None and offset >= remote_size:
            return url, True, f"Already complete ({offset} bytes)"

    headers: dict[str, str] = {}
    if offset > 0:
        headers["Range"] = f"bytes={offset}-"

    try:
        with session.get(url, timeout=TIMEOUT, headers=headers, stream=True) as r:
            r.raise_for_status()
            mode = "ab" if offset else "wb"
            with path.open(mode) as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
        return url, True, str(path)
    except requests.exceptions.RequestException as e:
        if MAX_RETRIES > 0:
            return url, False, f"Retry needed: {e}"
        return url, False, str(e)


def _make_session() -> requests.Session:
    """Create a requests Session with a generic User-Agent header."""
    session = requests.Session()
    session.headers.update(
        {"User-Agent": "Mozilla/5.0 (compatible; ResumableDownloader/1.0)"}
    )
    return session


def download_urls(urls: list[str], output_dir: str = OUTPUT_DIR) -> None:
    """Download the given URLs concurrently into output_dir."""
    Path(output_dir).mkdir(exist_ok=True, parents=True)

    safe_urls = [url for url in urls if is_safe_extension(url)]
    skipped = len(urls) - len(safe_urls)
    if skipped > 0:
        logger.warning(f"Skipped {skipped} URLs (not matching safe extensions).")

    if not safe_urls:
        logger.error("No valid URLs to download.")
        return

    print(f"Starting download of {len(safe_urls)} URLs...")

    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[tuple[str, bool, str]]] = [
            pool.apply_async(download_one, (url, _make_session(), output_dir))
            for url in safe_urls
        ]

        with tqdm(total=len(safe_urls), desc="Downloading", unit="file") as pbar:
            for url, ar in zip(safe_urls, async_results):
                try:
                    _, success, result = ar.get()
                    if success:
                        pbar.write(f"✅ {url.split('?')[0]} → {result}")
                    else:
                        pbar.write(f"❌ {url.split('?')[0]} failed: {result}")
                except Exception as e:
                    pbar.write(f"⚠️  Unexpected error for {url}: {e}")
                pbar.update(1)


def _read_urls(path: str) -> list[str]:
    """Read URLs from a file, ignoring blanks and comment lines."""
    with Path(path).open("r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def main(argv: Iterable[str] | None = None) -> int:
    """CLI entry point. Returns an exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    urls_file = args[0] if args else URLS_FILE

    if urls_file != URLS_FILE:
        print(f"Using input file: {urls_file}")

    try:
        urls = _read_urls(urls_file)
    except FileNotFoundError:
        logger.error(f"{urls_file} not found.")
        return 1

    if not urls:
        logger.warning(f"No URLs found in {urls_file}.")
        return 0

    download_urls(urls)
    print("All downloads completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
