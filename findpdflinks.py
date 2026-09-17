#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
import time
from collections import deque
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup


def can_fetch(rp: RobotFileParser, url):
    try:
        return rp.can_fetch("*", url)
    except Exception:
        return True


def crawl_for_pdfs(start_url: str, max_pages: int = 100, delay: float = 1.0):
    parsed = urlparse(start_url)
    if not parsed.scheme:
        start_url = "https://" + start_url.lstrip("/")
        parsed = urlparse(url)
    base_netloc = parsed.netloc
    rp = RobotFileParser()
    robots_url = urljoin(start_url, "/robots.txt")
    try:
        rp.set_url(robots_url)
        rp.read()
        print(f"✅ Loaded robots.txt: {robots_url}")
    except Exception as e:
        print(f"⚠️  Could not load robots.txt ({e}). Proceeding with caution.")
        rp = None
    visited = set()
    pdf_urls = set()
    queue = deque([start_url])
    headers = {"User-Agent": "PDF-Crawler/1.0 (non-commercial; see --help)"}
    while queue and len(visited) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        if rp and not can_fetch(rp, url):
            print(f"🚫 Skipping (robots.txt): {url}")
            continue
        visited.add(url)
        try:
            print(f"🔍 Checking: {url}")
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "").lower()
            if "pdf" in content_type:
                pdf_urls.add(url)
                print(f"  📄 PDF (via Content-Type): {url}")
                continue
            if "html" not in content_type and not url.lower().endswith(
                (".html", ".htm")
            ):
                continue
            soup = BeautifulSoup(resp.content, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                full_url = urljoin(url, href)
                if not full_url.startswith(("http://", "https://")):
                    continue
                if urlparse(full_url).netloc != base_netloc:
                    continue
                if full_url.lower().endswith(".pdf"):
                    pdf_urls.add(full_url)
                    print(f"  📄 PDF (via link): {full_url}")
                elif full_url not in visited:
                    if not any(
                        full_url.lower().endswith(ext)
                        for ext in (".jpg", ".jpeg", ".png", ".gif", ".css", ".js")
                    ):
                        queue.append(full_url)
        except requests.RequestException as e:
            print(f"  ⚠️  Request error: {e}")
        except Exception as e:
            print(f"  ⚠️  Unexpected error: {e}")
        time.sleep(delay)
    return sorted(pdf_urls)


def save_urls(urls, filename="urls.txt") -> None:
    with open(filename, "w", encoding="utf-8") as f:
        f.writelines(url + "\n" for url in urls)
    print(f"\n✅ Saved {len(urls)} PDF URLs to '{filename}'")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    start_url = sys.argv[1]
    max_pages = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    delay = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    if delay < 0.1:
        print("⚠️  Delay too low (<0.1s). Setting to 0.1s for safety.")
        delay = 0.1
    print(f"🔍 Starting crawl at: {start_url}")
    print(f"   Max pages: {max_pages}, Delay: {delay}s\n")
    pdf_urls = crawl_for_pdfs(start_url, max_pages, delay)
    save_urls(pdf_urls)


if __name__ == "__main__":
    raise SystemExit(main())
