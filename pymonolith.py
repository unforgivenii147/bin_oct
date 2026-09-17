#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import sys
from base64 import b64encode
from mimetypes import guess_type
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


class Monolith:
    def __init__(self, base_url, timeout=10, headers=None):
        self.base_url = base_url
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(headers or {"User-Agent": "Monolith/1.0"})
        self.cache = {}

    def fetch(self, url):
        if url in self.cache:
            return self.cache[url]
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            self.cache[url] = resp.content
            return resp.content
        except requests.RequestException as e:
            print(f"⚠ Failed to fetch {url}: {e}", file=sys.stderr)
            return None

    def to_data_uri(self, content, mime_type):
        if not content:
            return None
        b64 = b64encode(content).decode("ascii")
        return f"data:{mime_type};base64,{b64}"

    def resolve_url(self, url):
        if url.startswith(("http://", "https://")):
            return url
        if url.startswith("//"):
            scheme = urlparse(self.base_url).scheme
            return f"{scheme}:{url}"
        return urljoin(self.base_url, url)

    def guess_mime(self, url, fallback="application/octet-stream"):
        parsed = urlparse(url).path
        mime, _ = guess_type(parsed)
        return mime or fallback

    def process_stylesheets(self, soup):
        for link in soup.find_all("link", rel="stylesheet"):
            href = link.get("href")
            if not href:
                continue
            resolved = self.resolve_url(href)
            content = self.fetch(resolved)
            if content:
                data_uri = self.to_data_uri(content, "text/css")
                if data_uri:
                    link.attrs["href"] = data_uri

    def process_scripts(self, soup):
        for script in soup.find_all("script"):
            src = script.get("src")
            if not src:
                continue
            resolved = self.resolve_url(src)
            content = self.fetch(resolved)
            if content:
                script.string = content.decode("utf-8", errors="replace")
                del script.attrs["src"]

    def process_images(self, soup):
        for img in soup.find_all("img"):
            src = img.get("src")
            if not src:
                continue
            resolved = self.resolve_url(src)
            content = self.fetch(resolved)
            if content:
                mime = self.guess_mime(resolved, "image/png")
                data_uri = self.to_data_uri(content, mime)
                if data_uri:
                    img.attrs["src"] = data_uri

    def process_fonts(self, soup):
        for style in soup.find_all("style"):
            style.string = self._inline_font_urls(style.string or "")

    def _inline_font_urls(self, css_text):
        import re

        def replace_url(match):
            url = match.group(1)
            resolved = self.resolve_url(url)
            content = self.fetch(resolved)
            if content:
                mime = self.guess_mime(resolved, "font/woff2")
                data_uri = self.to_data_uri(content, mime)
                if data_uri:
                    return f"url({data_uri})"
            return match.group(0)

        return re.sub(r'url\([\'"]?([^\)\'\"]+)[\'"]?\)', replace_url, css_text)

    def convert(self):
        content = self.fetch(self.base_url)
        if not content:
            raise RuntimeError(f"Failed to fetch {self.base_url}")
        soup = BeautifulSoup(content, "html.parser")
        self.process_stylesheets(soup)
        self.process_scripts(soup)
        self.process_images(soup)
        self.process_fonts(soup)
        return str(soup.prettify())


def main():
    parser = argparse.ArgumentParser(
        description="Download a URL as a single, self-contained HTML file."
    )
    parser.add_argument("url", help="URL to download")
    parser.add_argument("-o", "--output", help="Output file (default: stdout)")
    parser.add_argument(
        "-t", "--timeout", type=int, default=10, help="Request timeout in seconds"
    )
    args = parser.parse_args()
    try:
        mono = Monolith(args.url, timeout=args.timeout)
        html = mono.convert()
        if args.output:
            Path(args.output).write_text(html, encoding="utf-8")
            print(f"✓ Saved to {args.output}", file=sys.stderr)
        else:
            print(html)
    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
