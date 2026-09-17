#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import hashlib
import multiprocessing as mp
from collections import deque
from io import BytesIO
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

MIN_WIDTH = 300
MIN_HEIGHT = 400
OUTPUT_FILE = Path("img_urls.txt")
DOWNLOAD_DIR = Path("images")


def normalize_url(url: str) -> str:
    url, _fragment = urldefrag(url)
    return url.rstrip("/") if urlparse(url).path else url


def is_http_url(url: str) -> bool:
    return urlparse(url).scheme in {"http", "https"}


def get_image_urls(soup: BeautifulSoup, page_url: str) -> set[str]:
    image_urls: set[str] = set()
    for image in soup.find_all("img"):
        for attribute in (
            "src",
            "data-src",
            "data-lazy-src",
            "data-original",
            "data-image",
        ):
            value = image.get(attribute)
            if value:
                image_url = normalize_url(urljoin(page_url, value.strip()))
                if is_http_url(image_url):
                    image_urls.add(image_url)
        srcset = image.get("srcset")
        if srcset:
            for candidate in srcset.split(","):
                image_url = candidate.strip().split(" ")[0]
                if image_url:
                    image_url = normalize_url(urljoin(page_url, image_url))
                    if is_http_url(image_url):
                        image_urls.add(image_url)
    return image_urls


def get_internal_links(
    soup: BeautifulSoup,
    page_url: str,
    site_netloc: str,
) -> set[str]:
    links: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        link = normalize_url(urljoin(page_url, anchor["href"]))
        if is_http_url(link) and urlparse(link).netloc == site_netloc:
            links.add(link)
    return links


def inspect_image(image_url: str) -> tuple[str, int, int] | None:
    try:
        response = requests.get(
            image_url,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "image/*",
            },
        )
        response.raise_for_status()
        if not response.headers.get("Content-Type", "").startswith("image/"):
            return None
        with Image.open(BytesIO(response.content)) as image:
            width, height = image.size
        if width > MIN_WIDTH and height > MIN_HEIGHT:
            return image_url, width, height
    except Exception:
        pass
    return None


def safe_filename(image_url: str) -> str:
    parsed = urlparse(image_url)
    original_name = Path(parsed.path).name or "image"
    suffix = Path(original_name).suffix.lower()
    if not suffix:
        suffix = ".img"
    stem = Path(original_name).stem or "image"
    unique_id = hashlib.sha256(image_url.encode()).hexdigest()[:12]
    return f"{stem}_{unique_id}{suffix}"


def download_image(item: tuple[str, int, int]) -> str | None:
    image_url, _width, _height = item
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    destination = DOWNLOAD_DIR / safe_filename(image_url)
    try:
        response = requests.get(
            image_url,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        destination.write_bytes(response.content)
        return str(destination)
    except Exception:
        return None


def crawl_site(
    start_url: str,
    max_pages: int,
    print_urls: bool,
    download_images: bool,
) -> None:
    start_url = normalize_url(start_url)
    site_netloc = urlparse(start_url).netloc
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    pages_to_visit = deque([start_url])
    visited_pages: set[str] = set()
    checked_images: set[str] = set()
    matches: list[tuple[str, int, int]] = []
    worker_count = max(1, mp.cpu_count() - 1)
    with mp.Pool(processes=worker_count) as pool:
        while pages_to_visit and len(visited_pages) < max_pages:
            page_url = pages_to_visit.popleft()
            if page_url in visited_pages:
                continue
            visited_pages.add(page_url)
            print(f"Scanning: {page_url}", flush=True)
            try:
                response = session.get(page_url, timeout=20)
                response.raise_for_status()
            except requests.RequestException as error:
                print(f"Could not scan page: {error}")
                continue
            if "text/html" not in response.headers.get("Content-Type", ""):
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            new_images = get_image_urls(soup, page_url) - checked_images
            checked_images.update(new_images)
            results = pool.map(inspect_image, new_images)
            for result in results:
                if result is not None:
                    matches.append(result)
            for link in get_internal_links(soup, page_url, site_netloc):
                if link not in visited_pages:
                    pages_to_visit.append(link)
        if print_urls:
            with OUTPUT_FILE.open("w", encoding="utf-8") as file:
                for image_url, width, height in matches:
                    print(f"{width}x{height} {image_url}")
                    file.write(f"{image_url}\n")
            print(f"Saved URLs to {OUTPUT_FILE}")
        if download_images:
            downloaded = pool.map(download_image, matches)
            successful = [path for path in downloaded if path is not None]
            print(f"Downloaded {len(successful)} image(s) to {DOWNLOAD_DIR}/")
    print(
        f"Scanned {len(visited_pages)} page(s), "
        f"checked {len(checked_images)} image(s), "
        f"found {len(matches)} matching image(s)."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find, print, save, and download large website images."
    )
    parser.add_argument(
        "url",
        help="Starting URL, for example https://example.com",
    )
    parser.add_argument(
        "-p",
        "--print",
        action="store_true",
        dest="print_urls",
        help="Print matching URLs and save them to img_urls.txt",
    )
    parser.add_argument(
        "-d",
        "--download",
        action="store_true",
        dest="download_images",
        help="Download matching images into the images/ directory",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=100,
        help="Maximum same-site pages to scan; default: 100",
    )
    args = parser.parse_args()
    if not is_http_url(args.url):
        parser.error("URL must start with http:// or https://")
    if not args.print_urls and not args.download_images:
        parser.error("Use -p, -d, or both")
    if args.max_pages < 1:
        parser.error("--max-pages must be at least 1")
    crawl_site(
        start_url=args.url,
        max_pages=args.max_pages,
        print_urls=args.print_urls,
        download_images=args.download_images,
    )


if __name__ == "__main__":
    mp.freeze_support()
    main()
