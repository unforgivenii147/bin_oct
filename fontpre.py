#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import html
import logging
import sys
from collections.abc import Generator
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
FONTEXT = frozenset({".ttf", ".otf", ".woff", ".woff2", ".eot", ".svg"})
SAMPLE_TEXT = "Lorem ipsum dolor sit amet\nهنر برتر از گوهر آمد پدید"
OUTPUT_FILE = "fontpreview.html"


class FontInfo(NamedTuple):
    path: Path
    index: int
    size: int
    format: str


def get_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def format_file_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


@lru_cache(maxsize=128)
def get_font_format(ext: str) -> str:
    format_map = {
        ".ttf": "TrueType",
        ".otf": "OpenType",
        ".woff": "WOFF",
        ".woff2": "WOFF2",
        ".eot": "Embedded OpenType",
        ".svg": "SVG Font",
    }
    return format_map.get(ext.lower(), ext.upper().lstrip("."))


def is_font_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in FONTEXT


def find_fonts_generator(
    roots: list[Path] | None = None,
) -> Generator[Path, None, None]:
    if not roots:
        roots = [Path.cwd()]
    visited = set()
    for root in roots:
        try:
            root = root.resolve()
            if not root.exists():
                logger.warning(f"Path does not exist: {root}")
                continue
            if root.is_file():
                if is_font_file(root):
                    yield root
            else:
                for path in root.rglob("*"):
                    if path in visited:
                        continue
                    visited.add(path)
                    if is_font_file(path):
                        try:
                            yield path
                        except (OSError, ValueError) as e:
                            logger.debug(f"Skipping {path}: {e}")
        except (PermissionError, OSError) as e:
            logger.warning(f"Cannot access {root}: {e}")


def collect_fonts(
    roots: list[Path] | None = None, max_fonts: int = 10000
) -> list[FontInfo]:
    fonts: list[FontInfo] = []
    for i, path in enumerate(find_fonts_generator(roots), 1):
        if i > max_fonts:
            logger.warning(f"Reached maximum font limit ({max_fonts})")
            break
        try:
            stat = path.stat()
            font_info = FontInfo(
                path=path,
                index=i,
                size=stat.st_size,
                format=get_font_format(path.suffix),
            )
            fonts.append(font_info)
        except (OSError, ValueError) as e:
            logger.debug(f"Error processing {path}: {e}")
            continue
    return sorted(fonts, key=lambda f: (f.path.parent, f.path.name))


def create_font_face(font_info: FontInfo, cwd: Path) -> str:
    try:
        rel_path = font_info.path.relative_to(cwd)
        url_path = quote(rel_path.as_posix())
    except ValueError:
        url_path = quote(font_info.path.as_posix())
        if not url_path.startswith("/"):
            url_path = "/" + url_path
    font_id = f"{font_info.index:04d}"
    return f"""@font-face {{
  font-family: 'font_{font_id}';
  src: url('{url_path}');
  font-display: swap;
  font-weight: normal;
  font-style: normal;
}}"""


def create_font_section(font_info: FontInfo, cwd: Path) -> str:
    font_id = f"{font_info.index:04d}"
    font_name = font_info.path.name
    try:
        display_path = font_info.path.relative_to(cwd)
    except ValueError:
        display_path = font_info.path
    escaped_name = html.escape(font_name)
    escaped_path = html.escape(str(display_path))
    escaped_sample = html.escape(SAMPLE_TEXT)
    size_str = format_file_size(font_info.size)
    return f"""
<section>
  <h1 style="font-family: 'font_{font_id}', serif;">
    {escaped_name}
    <small>({font_info.format})</small>
  </h1>
  <textarea
    style="font-family: 'font_{font_id}', serif; font-size: 22px;"
    spellcheck="false"
    placeholder="Type to test font..."
  >{escaped_sample}</textarea>
  <div class="metadata">
    <div class="metadata-item">
      <span class="metadata-label">Path:</span>
      <code>{escaped_path}</code>
    </div>
    <div class="metadata-item">
      <span class="metadata-label">Size:</span>
      <code>{size_str}</code>
    </div>
    <div class="metadata-item">
      <span class="metadata-label">Format:</span>
      <code>{font_info.format}</code>
    </div>
  </div>
</section>"""


def generate_preview_styles(fonts: list[FontInfo], cwd: Path) -> str:
    return "\n\n".join(create_font_face(font, cwd) for font in fonts)


def generate_preview_sections(fonts: list[FontInfo], cwd: Path) -> str:
    return "\n".join(create_font_section(font, cwd) for font in fonts)


def generate_html(fonts: list[FontInfo], cwd: Path) -> str:
    timestamp = get_timestamp()
    html_start = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Font Preview</title>
<style>
:root {{
  --bg:
  --text:
  --border:
  --accent:
  --input-bg:
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg:
    --text:
    --border:
    --accent:
    --input-bg:
  }}
}}
* {{
  box-sizing: border-box;
}}
body {{
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, -apple-system, sans-serif;
  margin: 0 auto;
  padding: 20px;
  max-width: 960px;
  transition: background 0.3s, color 0.3s;
}}
h1 {{
  margin-top: 40px;
  margin-bottom: 0.5em;
  font-size: 1.6em;
  border-bottom: 2px solid var(--border);
  padding-bottom: 0.3em;
  color: var(--accent);
  word-break: break-word;
}}
h1 small {{
  font-size: 0.6em;
  opacity: 0.7;
  display: inline-block;
  margin-left: 0.5em;
}}
textarea {{
  width: 100%;
  min-height: 100px;
  padding: 16px;
  margin-top: 6px;
  border-radius: 8px;
  border: 2px solid var(--border);
  font-size: clamp(1em, 2vw, 1.5em);
  resize: vertical;
  white-space: pre-wrap;
  background: var(--input-bg);
  color: var(--text);
  transition: border-color 0.3s;
  line-height: 1.6;
  overflow-wrap: break-word;
}}
textarea:focus {{
  outline: none;
  border-color: var(--accent);
}}
section {{
  margin-top: 30px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--border);
}}
section:last-of-type {{
  border-bottom: none;
}}
.note {{
  color: var(--text);
  margin-top: 8px;
  font-size: 0.85em;
  font-family: monospace;
  word-break: break-all;
  opacity: 0.75;
}}
footer {{
  margin-top: 40px;
  text-align: center;
  color: var(--text);
  font-size: 0.9em;
  opacity: 0.6;
}}
.metadata {{
  display: flex;
  gap: 16px;
  font-size: 0.9em;
  margin-top: 8px;
  flex-wrap: wrap;
}}
.metadata-item {{
  display: flex;
  align-items: center;
  gap: 4px;
}}
.metadata-label {{
  opacity: 0.7;
  font-weight: 500;
}}
</style>
</head>
<body>
<h1>Font Preview Generator</h1>
<p class="note">Generated: {timestamp}</p>
<style>
"""
    html_middle = """
</style>
"""
    html_end = """
<footer>
Generated by Font Preview Generator | Python 3.12+ | Pathlib optimized
</footer>
</body>
</html>
"""
    if not fonts:
        return f"{html_start}{html_middle}{html_end}"
    styles = generate_preview_styles(fonts, cwd)
    sections = generate_preview_sections(fonts, cwd)
    return f"{html_start}{styles}{html_middle}{sections}{html_end}"


def write_preview(html_content: str, output_path: Path) -> bool:
    try:
        temp_path = output_path.with_suffix(".tmp")
        temp_path.write_text(html_content, encoding="utf-8")
        temp_path.replace(output_path)
        return True
    except OSError as e:
        logger.error(f"Failed to write {output_path}: {e}")
        return False


def validate_paths(paths: list[str] | None) -> list[Path]:
    if not paths:
        return [Path.cwd()]
    validated = []
    for path_str in paths:
        try:
            path = Path(path_str).expanduser().resolve()
            if path.exists():
                validated.append(path)
            else:
                logger.warning(f"Path does not exist: {path_str}")
        except (OSError, ValueError) as e:
            logger.warning(f"Invalid path '{path_str}': {e}")
    return validated if validated else [Path.cwd()]


def main(input_paths: list[str] | None = None, output_file: str = OUTPUT_FILE) -> int:
    cwd = Path.cwd()
    valid_paths = validate_paths(input_paths)
    print(f"Searching for fonts in {len(valid_paths)} location(s)...")
    fonts = collect_fonts(valid_paths)
    if not fonts:
        logger.warning(
            f"No font files found. Supported formats: {', '.join(sorted(FONTEXT))}"
        )
        return 1
    print(f"Found {len(fonts)} font(s)")
    print("Generating preview HTML...")
    html_content = generate_html(fonts, cwd)
    output_path = cwd / output_file
    print(f"Writing to {output_path}...")
    if write_preview(html_content, output_path):
        print(f"✓ Successfully generated {output_path}")
        print(f"  File size: {format_file_size(output_path.stat().st_size)}")
        return 0
    else:
        return 1


def cli_main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate interactive HTML preview for font files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  fontpreview.py
  fontpreview.py ./fonts/
  fontpreview.py ./fonts/ ~/Downloads/ ./local/
  fontpreview.py -o my_preview.html ./fonts/
        """,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="File or directory paths to process (default: current directory)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=OUTPUT_FILE,
        help=f"Output HTML filename (default: {OUTPUT_FILE})",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    args = parser.parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    try:
        exit_code = main(args.paths if args.paths else None, args.output)
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.warning("Operation cancelled by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    cli_main()
