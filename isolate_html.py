#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from bs4.element import AttributeValueList


class HTMLStandaloneMaker:
    MIME_MAP = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
        ".ico": "image/x-icon",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
        ".otf": "font/otf",
        ".eot": "application/vnd.ms-fontobject",
        ".js": "application/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".xml": "application/xml",
        ".txt": "text/plain",
    }

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.embedded_count = 0
        self.warning_count = 0

    def log(self, message: str, level: str = "INFO") -> None:
        if self.verbose or level == "ERROR":
            print(f"[{level}] {message}")

    def get_mime_type(self, path: Path) -> str:
        ext = path.suffix.lower()
        return self.MIME_MAP.get(ext, "application/octet-stream")

    def encode_local_file_to_base64(self, path: Path) -> str | None:
        try:
            if not path.exists():
                self.log(f"File not found: {path}", "ERROR")
                return None
            content = path.read_bytes()
            return base64.b64encode(content).decode("utf-8")
        except Exception as e:
            self.log(f"Error encoding file {path}: {e}", "ERROR")
            return None

    def find_local_resource(
        self, resource_name: str | AttributeValueList, base_dir: Path
    ) -> Path | None:
        resource_str = str(resource_name)
        parsed = urlparse(resource_str)
        path_part = parsed.path.lstrip("/")
        search_locations = [
            base_dir,
            Path("/sdcard/_static"),
            Path.cwd(),
            base_dir.parent.parent,
            base_dir.parent,
        ]
        for location in search_locations:
            location = location.resolve()
            candidate = location / resource_str
            if candidate.exists():
                self.log(f"Found resource '{resource_str}' at: {candidate}")
                return candidate
            if resource_str.startswith("/"):
                candidate = location / path_part
                if candidate.exists():
                    self.log(
                        f"Found resource '{resource_str}' (stripped) at: {candidate}"
                    )
                    return candidate
            candidate = location / Path(resource_str).name
            if candidate.exists():
                self.log(
                    f"Found resource '{resource_str}' (filename only) at: {candidate}"
                )
                return candidate
        self.log(f"Resource '{resource_str}' not found in search locations", "WARNING")
        self.warning_count += 1
        return None

    def process_css_content(self, css_content: str, css_dir: Path) -> str:
        if not css_content:
            return css_content
        font_url_pattern = "url\\s*\\(\\s*['\\\"]?([^'\\\")]+)['\\\"]?\\s*\\)"
        font_url_matches = re.findall(font_url_pattern, css_content, re.IGNORECASE)
        for font_url in font_url_matches:
            if font_url.startswith(("http://", "https://", "data:")):
                continue
            local_font_path = self.find_local_resource(font_url, css_dir)
            if local_font_path:
                encoded_font = self.encode_local_file_to_base64(local_font_path)
                if encoded_font:
                    mime_type = self.get_mime_type(local_font_path)
                    escaped_url = re.escape(f"url({font_url})")
                    escaped_url = escaped_url.replace("\\(", "\\(").replace(
                        "\\)", "\\)"
                    )
                    css_content = re.sub(
                        escaped_url,
                        f"url('data:{mime_type};base64,{encoded_font}')",
                        css_content,
                        flags=re.IGNORECASE,
                    )
                    self.embedded_count += 1
                    self.log(f"Embedded font: {local_font_path.name}")
            else:
                self.log(
                    f"Font file '{font_url}' not found, leaving reference", "WARNING"
                )
        return css_content

    def process_image_tag(self, img_tag, base_dir: Path) -> None:
        src = img_tag.get("src")
        if not src or src.startswith(("http://", "https://", "data:")):
            return
        local_img_path = self.find_local_resource(src, base_dir)
        if local_img_path:
            encoded_img = self.encode_local_file_to_base64(local_img_path)
            if encoded_img:
                mime_type = self.get_mime_type(local_img_path)
                img_tag["src"] = f"data:{mime_type};base64,{encoded_img}"
                self.embedded_count += 1
                self.log(f"Embedded image: {local_img_path.name}")
        else:
            self.log(f"Image '{src}' not found, removing tag", "WARNING")
            img_tag.decompose()

    def process_link_tag(self, link_tag, base_dir: Path) -> None:
        if link_tag.get("rel") != ["stylesheet"]:
            return
        href = link_tag.get("href")
        if not href or href.startswith(("http://", "https://", "data:")):
            return
        local_css_path = self.find_local_resource(href, base_dir)
        if local_css_path:
            try:
                css_content = local_css_path.read_text(encoding="utf-8")
                css_content = self.process_css_content(
                    css_content, local_css_path.parent
                )
                style_tag = BeautifulSoup("", "html.parser").new_tag("style")
                style_tag.string = css_content
                link_tag.replace_with(style_tag)
                self.log(f"Embedded CSS: {local_css_path.name}")
            except Exception as e:
                self.log(f"Error processing CSS {local_css_path}: {e}", "ERROR")
                link_tag.decompose()
        else:
            self.log(f"CSS '{href}' not found, removing link", "WARNING")
            link_tag.decompose()

    def process_script_tag(self, script_tag, base_dir: Path) -> None:
        src = script_tag.get("src")
        if not src:
            return
        if src.startswith(("http://", "https://")):
            self.log(f"Removing external script: {src}")
            script_tag.decompose()
            return
        local_script_path = self.find_local_resource(src, base_dir)
        if local_script_path:
            try:
                script_content = local_script_path.read_text(encoding="utf-8")
                script_tag.string = script_content
                script_tag["src"] = ""
                self.log(f"Embedded script: {local_script_path.name}")
            except Exception as e:
                self.log(f"Error reading script {local_script_path}: {e}", "ERROR")
                script_tag.decompose()
        else:
            self.log(f"Script '{src}' not found, removing tag", "WARNING")
            script_tag.decompose()

    def process_inline_styles(self, style_tag, base_dir: Path) -> None:
        style_content = style_tag.string
        if style_content:
            processed_content = self.process_css_content(style_content, base_dir)
            style_tag.string = processed_content

    def make_html_standalone(self, html_path: Path) -> str | None:
        try:
            html_content = html_path.read_text(encoding="utf-8")
        except Exception as e:
            self.log(f"Error reading HTML file {html_path}: {e}", "ERROR")
            return None
        soup = BeautifulSoup(html_content, "html.parser")
        base_dir = html_path.parent
        self.log(f"Processing HTML: {html_path.name}")
        self.log(f"Base directory: {base_dir}")
        for img_tag in soup.find_all("img"):
            self.process_image_tag(img_tag, base_dir)
        for link_tag in soup.find_all("link"):
            self.process_link_tag(link_tag, base_dir)
        for script_tag in soup.find_all("script"):
            self.process_script_tag(script_tag, base_dir)
        for style_tag in soup.find_all("style"):
            self.process_inline_styles(style_tag, base_dir)
        self.log(f"Embedded {self.embedded_count} resources")
        self.log(f"Warnings: {self.warning_count}")
        return soup.prettify()

    def save_standalone(self, html_path: Path, output_path: Path | None = None) -> bool:
        standalone_html = self.make_html_standalone(html_path)
        if not standalone_html:
            return False
        if output_path is None:
            output_path = (
                html_path.parent / f"{html_path.stem}_standalone{html_path.suffix}"
            )
        try:
            output_path.write_text(standalone_html, encoding="utf-8")
            self.log(f"Standalone HTML saved to: {output_path}")
            return True
        except Exception as e:
            self.log(f"Error writing to output file {output_path}: {e}", "ERROR")
            return False


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert HTML to standalone by embedding all resources",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n  python html_standalone.py index.html\n  python html_standalone.py index.html -o standalone.html\n  python html_standalone.py index.html -v\n  python html_standalone.py index.html --no-embed-scripts\n        ",
    )
    parser.add_argument("input", help="Input HTML file")
    parser.add_argument(
        "-o", "--output", help="Output file (default: input_standalone.html)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument(
        "--no-embed-scripts", action="store_true", help="Don't embed scripts"
    )
    parser.add_argument(
        "--no-embed-images", action="store_true", help="Don't embed images"
    )
    parser.add_argument(
        "--no-embed-fonts", action="store_true", help="Don't embed fonts"
    )
    args = parser.parse_args()
    try:
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"Error: Input file not found: {args.input}")
            sys.exit(1)
        maker = HTMLStandaloneMaker(verbose=args.verbose)
        if args.output:
            output_path = Path(args.output)
        else:
            output_path = (
                input_path.parent / f"{input_path.stem}_standalone{input_path.suffix}"
            )
        success = maker.save_standalone(input_path, output_path)
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
