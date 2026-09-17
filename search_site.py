#!/data/data/com.termux/files/home/.local/bin/python
import sys
import time
from collections import deque
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

if len(sys.argv) < 3:
    print("Usage: python script.py <site> <keyword>")
    print("Example: python script.py https://subdl.com shameless")
    sys.exit(1)

BASE = sys.argv[1].rstrip("/")
KEYWORD = sys.argv[2].lower()

if not BASE.startswith(("http://", "https://")):
    BASE = "https://" + BASE

BASE_HOST = urlparse(BASE).netloc.lower().split(":")[0]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; URLCollector/1.0; +https://example.com/bot)"
}

session = requests.Session()
session.headers.update(HEADERS)

# Respect robots.txt
rp = RobotFileParser()
rp.set_url(urljoin(BASE, "/robots.txt"))
try:
    rp.read()
except Exception:
    pass


def allowed(url):
    try:
        return rp.can_fetch(HEADERS["User-Agent"], url)
    except Exception:
        return True


def is_internal(url):
    host = urlparse(url).netloc.lower().split(":")[0]
    return host == BASE_HOST or host.endswith("." + BASE_HOST)


def clean_url(url):
    p = urlparse(url)
    return p._replace(fragment="").geturl()


def crawl(start_urls, max_pages=3000, delay=0.5):
    queue = deque(start_urls)
    seen = set()
    found = set()

    while queue and len(seen) < max_pages:
        url = clean_url(queue.popleft())

        if url in seen or not allowed(url):
            continue

        seen.add(url)
        print("Checking:", url)

        if KEYWORD in url.lower():
            found.add(url)

        try:
            r = session.get(url, timeout=20)
            r.raise_for_status()
        except Exception as e:
            print("Error:", url, e)
            continue

        if "text/html" not in r.headers.get("content-type", ""):
            continue

        soup = BeautifulSoup(r.text, "html.parser")

        for a in soup.find_all("a", href=True):
            next_url = clean_url(urljoin(url, a["href"]))

            if not is_internal(next_url):
                continue

            if KEYWORD in next_url.lower():
                found.add(next_url)

            if next_url not in seen:
                queue.append(next_url)

        time.sleep(delay)  # be polite

    return found


if __name__ == "__main__":
    start_urls = [BASE]

    urls = crawl(start_urls, max_pages=3000, delay=0.5)

    out_file = f"{KEYWORD}_urls.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        f.writelines(u + "\n" for u in sorted(urls))

    print(f"Found {len(urls)} URLs")
    print(f"Saved to {out_file}")
