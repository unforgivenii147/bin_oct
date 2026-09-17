#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


class Monolith:
    MIME_TYPES = {
        ".css": "text/css",
        ".js": "application/javascript",
        ".svg": "image/svg+xml",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
        ".eot": "application/vnd.ms-fontobject",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }

    def __init__(
        self, ignore_errors=False, no_images=False, timeout=10, encoding="utf-8"
    ):
        self.ignore_errors = ignore_errors
        self.no_images = no_images
        self.timeout = timeout
        self.encoding = encoding
        self.base_url = None
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Monolith/1.0"}
        )
        self.fetched_resources = {}

    def fetch_resource(self, url):
        if url in self.fetched_resources:
            return self.fetched_resources[url]
        try:
            response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            response.raise_for_status()
            content = response.content
            self.fetched_resources[url] = content
            return content
        except Exception as e:
            if not self.ignore_errors:
                raise
            print(f"⚠ Skipping unreachable resource: {url}", file=sys.stderr)
            return b""

    def resource_to_data_uri(self, url, mime_type=None):
        content = self.fetch_resource(url)
        if not content:
            return ""
        if not mime_type:
            ext = Path(urlparse(url).path).suffix.lower()
            mime_type = self.MIME_TYPES.get(ext, "application/octet-stream")
        b64 = base64.b64encode(content).decode("ascii")
        return f"data:{mime_type};base64,{b64}"

    def inline_css(self, soup):
        for link in soup.find_all("link", rel="stylesheet"):
            href = link.get("href")
            if not href:
                continue
            url = urljoin(self.base_url, href)
            try:
                css_content = self.fetch_resource(url).decode("utf-8", errors="ignore")
                css_content = self._rebase_css_urls(css_content, url)
                style = soup.new_tag("style")
                style["type"] = "text/css"
                style.string = css_content
                link.replace(style)
            except Exception as e:
                if not self.ignore_errors:
                    raise
                print(f"⚠ Skipping CSS: {url}", file=sys.stderr)

    def _rebase_css_urls(self, css, base_url):
        def replace_url(match):
            url = match.group(1).strip("'\"")
            if url.startswith(("data:", "#")):
                return match.group(0)
            absolute_url = urljoin(base_url, url)
            try:
                data_uri = self.resource_to_data_uri(absolute_url)
                return f"url('{data_uri}')" if data_uri else match.group(0)
            except Exception:
                if not self.ignore_errors:
                    raise
                return match.group(0)

        return re.sub(r'url\([\'"]?([^\)]+)[\'"]?\)', replace_url, css)

    def inline_scripts(self, soup):
        for script in soup.find_all("script", src=True):
            src = script.get("src")
            if not src:
                continue
            url = urljoin(self.base_url, src)
            try:
                js_content = self.fetch_resource(url).decode("utf-8", errors="ignore")
                script["src"] = None
                script.string = js_content
            except Exception as e:
                if not self.ignore_errors:
                    raise
                print(f"⚠ Skipping script: {url}", file=sys.stderr)

    def inline_images(self, soup):
        if self.no_images:
            for img in soup.find_all("img"):
                img.decompose()
            return
        for img in soup.find_all("img"):
            src = img.get("src")
            if not src:
                continue
            url = urljoin(self.base_url, src)
            try:
                data_uri = self.resource_to_data_uri(url)
                if data_uri:
                    img["src"] = data_uri
            except Exception as e:
                if not self.ignore_errors:
                    raise
                print(f"⚠ Skipping image: {url}", file=sys.stderr)
        for element in soup.find_all(srcset=True):
            srcset = element.get("srcset", "")
            new_srcset = []
            for part in srcset.split(","):
                part = part.strip()
                if not part:
                    continue
                tokens = part.split()
                url = tokens[0]
                descriptor = " ".join(tokens[1:]) if len(tokens) > 1 else ""
                abs_url = urljoin(self.base_url, url)
                try:
                    data_uri = self.resource_to_data_uri(abs_url)
                    if data_uri:
                        new_srcset.append(f"{data_uri} {descriptor}".strip())
                except Exception:
                    if not self.ignore_errors:
                        raise
            if new_srcset:
                element["srcset"] = ", ".join(new_srcset)

    def inline_fonts(self, soup):
        for style in soup.find_all("style"):
            if not style.string:
                continue
            css = style.string
            css = self._rebase_css_urls(css, self.base_url)
            style.string = css

    def process_html(self, html_content, source_url=None):
        self.base_url = source_url or "http://localhost/"
        soup = BeautifulSoup(html_content, "html.parser")
        meta = soup.find("meta", charset=True)
        if not meta:
            meta = soup.new_tag("meta", charset=self.encoding)
            head = soup.find("head")
            if head:
                head.insert(0, meta)
            else:
                html_tag = soup.find("html")
                new_head = soup.new_tag("head")
                new_head.append(meta)
                if html_tag:
                    html_tag.insert(0, new_head)
        else:
            meta["charset"] = self.encoding
        self.inline_css(soup)
        self.inline_scripts(soup)
        self.inline_images(soup)
        self.inline_fonts(soup)
        return str(soup)

    def from_url(self, url):
        print(f"📥 Fetching {url}...", file=sys.stderr)
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        html = response.text
        return self.process_html(html, url)

    def from_file(self, path):
        path = Path(path).resolve()
        print(f"📂 Loading {path}...", file=sys.stderr)
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            html = f.read()
        file_url = path.as_uri()
        return self.process_html(html, file_url)


def main():
    parser = argparse.ArgumentParser(
        description="Save webpages as single HTML files with embedded resources",
        prog="monolith",
    )
    parser.add_argument("source", help="URL or local file path")
    parser.add_argument(
        "-e",
        "--ignore-errors",
        action="store_true",
        help="Ignore unreachable resources (continue on errors)",
    )
    parser.add_argument(
        "-i", "--no-images", action="store_true", help="Strip all images from output"
    )
    parser.add_argument("-o", "--output", help="Output file path (default: stdout)")
    args = parser.parse_args()
    try:
        monolith = Monolith(ignore_errors=args.ignore_errors, no_images=args.no_images)
        if args.source.startswith(("http://", "https://")):
            html = monolith.from_url(args.source)
        else:
            html = monolith.from_file(args.source)
        if args.output:
            output_path = Path(args.output)
            print(f"💾 Writing to {output_path}...", file=sys.stderr)
            output_path.write_text(html, encoding="utf-8")
            print(f"✅ Done! Saved to {output_path}", file=sys.stderr)
        else:
            print(html)
    except requests.RequestException as e:
        print(f"❌ Network error: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"❌ File not found: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
