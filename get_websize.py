#!/data/data/com.termux/files/home/.local/bin/python
"""
Measure total download size of a website by fetching HTML, CSS, JS, images, fonts, etc.
Works well for documentation sites (docs.astral.sh, readthedocs.io, etc.)
"""

import argparse
import sys
from collections import defaultdict
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Resource types we care about
RESOURCE_ATTRS = {
    "link": ["href"],  # CSS, icons, fonts, preload
    "script": ["src"],  # JS
    "img": ["src", "srcset"],
    "source": ["src", "srcset"],
    "video": ["src", "poster"],
    "audio": ["src"],
    "iframe": ["src"],
    "embed": ["src"],
    "object": ["data"],
}


def normalize_urls(base_url: str, value: str) -> list[str]:
    """Handle srcset (comma-separated list with descriptors) and plain URLs."""
    urls = []
    for part in value.split(","):
        url = part.strip().split(" ")[0]
        if url:
            urls.append(urljoin(base_url, url))
    return urls


def fetch_size(session: requests.Session, url: str):
    """Return (url, size_in_bytes) or None on failure."""
    try:
        # Use GET so we actually download content (HEAD isn't always accurate/reliable)
        resp = session.get(url, stream=True, timeout=15, allow_redirects=True)
        size = 0
        for chunk in resp.iter_content(chunk_size=8192):
            size += len(chunk)
        return size, resp.headers.get("content-type", "").split(";")[0]
    except requests.RequestException as e:
        print(f"  ! Failed: {url} ({e})", file=sys.stderr)
        return None


def get_resource_urls(session: requests.Session, url: str) -> list[str]:
    """Fetch an HTML page and return all resource URLs referenced in it."""
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ! Could not fetch HTML {url}: {e}", file=sys.stderr)
        return []

    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    urls = set()

    for tag_name, attrs in RESOURCE_ATTRS.items():
        for tag in soup.find_all(tag_name):
            for attr in attrs:
                value = tag.get(attr)
                if not value:
                    continue
                if attr == "srcset":
                    for u in normalize_urls(url, value):
                        urls.add(u)
                else:
                    urls.add(urljoin(url, value))

    # Also include <style> inline blocks? No — they're part of the HTML already.
    return list(urls)


def human_size(num_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.2f} TB"


def main():
    parser = argparse.ArgumentParser(
        description="Measure total download size of a website."
    )
    parser.add_argument("url", help="Starting URL, e.g. https://docs.astral.sh/ty/")
    parser.add_argument(
        "--crawl",
        action="store_true",
        help="Follow same-domain links and measure each page (slower).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=50,
        help="Max pages to crawl when --crawl is used (default: 50).",
    )
    parser.add_argument(
        "--user-agent",
        default="Mozilla/5.0 (size-checker)",
        help="User-Agent string to send.",
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = args.user_agent

    start = args.url
    domain = urlparse(start).netloc

    # Track resources so we don't double-count shared CSS/JS/fonts
    seen_resources: set[str] = set()
    pages_to_visit = [start]
    visited_pages: set[str] = set()

    total = 0
    html_bytes = 0
    per_type = defaultdict(int)
    resource_count = 0

    while pages_to_visit:
        page = pages_to_visit.pop(0)
        if page in visited_pages:
            continue
        visited_pages.add(page)

        if args.crawl and len(visited_pages) > args.max_pages:
            break

        print(f"\n>> Page: {page}")
        # Fetch HTML and count it
        try:
            resp = session.get(page, timeout=15)
            resp.raise_for_status()
            html_len = len(resp.content)
            total += html_len
            html_bytes += html_len
            per_type["text/html"] += html_len
            print(f"   HTML: {human_size(html_len)}")
        except requests.RequestException as e:
            print(f"   ! Failed: {e}", file=sys.stderr)
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        # Collect resources
        for tag_name, attrs in RESOURCE_ATTRS.items():
            for tag in soup.find_all(tag_name):
                for attr in attrs:
                    value = tag.get(attr)
                    if not value:
                        continue
                    urls = (
                        normalize_urls(page, value)
                        if attr == "srcset"
                        else [urljoin(page, value)]
                    )
                    for u in urls:
                        if u in seen_resources:
                            continue
                        seen_resources.add(u)
                        result = fetch_size(session, u)
                        if result is None:
                            continue
                        size, ctype = result
                        total += size
                        per_type[ctype or "unknown"] += size
                        resource_count += 1

        # Optionally crawl same-domain pages
        if args.crawl:
            for a in soup.find_all("a", href=True):
                link = urljoin(page, a["href"])
                p = urlparse(link)
                if p.netloc == domain and p.scheme in ("http", "https"):
                    # Strip fragments
                    clean = p._replace(fragment="").geturl()
                    if clean not in visited_pages:
                        pages_to_visit.append(clean)

    # Report
    print("\n" + "=" * 60)
    print(f"Pages visited:      {len(visited_pages)}")
    print(f"Sub-resources:      {resource_count}")
    print(f"HTML total:         {human_size(html_bytes)}")
    print(f"TOTAL DOWNLOAD:     {human_size(total)}")
    print("=" * 60)
    print("\nBreakdown by content-type:")
    for ctype, size in sorted(per_type.items(), key=lambda x: -x[1]):
        print(f"  {ctype:<30} {human_size(size):>12}")


if __name__ == "__main__":
    main()
