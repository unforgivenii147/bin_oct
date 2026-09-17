#!/data/data/com.termux/files/home/.local/bin/python
"""
HTML Asset Extractor - Extract inline CSS and JavaScript to separate files.

This script processes HTML files to extract inline <style> and <script> tags,
saves them as separate files in an assets directory, and updates the HTML
to reference these external files.

Usage:
    python extract_assets.py [files/dirs...]

If no arguments provided, processes all HTML files in current directory recursively.
"""

import argparse
import hashlib
import html.parser
import multiprocessing as mp
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

# Configuration
NUM_WORKERS = 8
ASSETS_DIR_NAME = "assets"
CSS_SUBDIR = "css"
JS_SUBDIR = "js"
HTML_EXTENSIONS = {".html", ".htm"}
MIN_INLINE_SIZE = 0  # Minimum size in bytes to extract (0 = extract all)


@dataclass
class ExtractionResult:
    """Result of processing a single HTML file."""

    path: Path
    success: bool
    css_count: int = 0
    js_count: int = 0
    error: str | None = None


class HTMLExtractor(html.parser.HTMLParser):
    """
    Streaming HTML parser that identifies and extracts inline <style> and <script> tags.

    Uses a streaming approach to minimize memory usage for large files.
    """

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.reset_state()
        self.extractions: list[tuple[str, str, dict]] = []  # (type, content, attrs)

    def reset_state(self):
        """Reset parser state for reuse."""
        self.current_tag = None
        self.current_attrs = {}
        self.current_content = []
        self.in_style = False
        self.in_script = False
        self.script_has_src = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        """Handle opening tags."""
        tag_lower = tag.lower()

        if tag_lower == "style":
            self.in_style = True
            self.current_attrs = dict(attrs)
            self.current_content = []

        elif tag_lower == "script":
            attrs_dict = dict(attrs)
            # Only process inline scripts (no src attribute)
            if "src" not in attrs_dict:
                self.in_script = True
                self.script_has_src = False
                self.current_attrs = attrs_dict
                self.current_content = []
            else:
                self.script_has_src = True

    def handle_endtag(self, tag: str):
        """Handle closing tags."""
        tag_lower = tag.lower()

        if tag_lower == "style" and self.in_style:
            content = "".join(self.current_content).strip()
            if content and len(content) >= MIN_INLINE_SIZE:
                self.extractions.append(("css", content, self.current_attrs))
            self.in_style = False
            self.current_content = []

        elif tag_lower == "script" and self.in_script:
            content = "".join(self.current_content).strip()
            if content and len(content) >= MIN_INLINE_SIZE:
                self.extractions.append(("js", content, self.current_attrs))
            self.in_script = False
            self.current_content = []

    def handle_data(self, data: str):
        """Collect content within style/script tags."""
        if self.in_style or self.in_script:
            self.current_content.append(data)

    def handle_entityref(self, name: str):
        """Handle entity references within script/style."""
        if self.in_script:  # Scripts can contain entity-like content
            self.current_content.append(f"&{name};")

    def handle_charref(self, name: str):
        """Handle character references within script/style."""
        if self.in_script:
            self.current_content.append(f"&#{name};")

    def error(self, message: str):
        """Handle parser errors gracefully."""
        pass  # Continue parsing despite errors


def compute_content_hash(content: str) -> str:
    """Compute a short hash for content-based filenames."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


def get_unique_filename(base_name: str, extension: str, assets_dir: Path) -> str:
    """
    Generate a unique filename, avoiding collisions.

    Args:
        base_name: Base name for the file
        extension: File extension (with dot)
        assets_dir: Directory where file will be saved

    Returns:
        Unique filename
    """
    filename = f"{base_name}{extension}"
    counter = 1

    while (assets_dir / filename).exists():
        filename = f"{base_name}_{counter}{extension}"
        counter += 1

    return filename


def extract_assets_from_html(
    html_content: str, html_path: Path, assets_base_dir: Path
) -> tuple[str, int, int]:
    """
    Extract inline CSS and JS from HTML content and return modified HTML.

    Args:
        html_content: Original HTML content
        html_path: Path to original HTML file (for naming)
        assets_base_dir: Base directory for assets

    Returns:
        Tuple of (modified_html, css_count, js_count)
    """
    parser = HTMLExtractor()

    try:
        parser.feed(html_content)
        parser.close()
    except Exception:
        # Return original content on parse failure
        return html_content, 0, 0

    if not parser.extractions:
        return html_content, 0, 0

    # Create asset directories
    css_dir = assets_base_dir / CSS_SUBDIR
    js_dir = assets_base_dir / JS_SUBDIR
    css_dir.mkdir(parents=True, exist_ok=True)
    js_dir.mkdir(parents=True, exist_ok=True)

    # Calculate relative path from HTML file to assets
    try:
        rel_assets_path = assets_base_dir.relative_to(html_path.parent)
    except ValueError:
        # assets dir is not under html's parent, use relative path
        rel_assets_path = Path(*[".."] * len(html_path.parent.parts)) / assets_base_dir

    # Prepare replacements
    replacements: list[tuple[str, str]] = []
    css_count = 0
    js_count = 0

    html_stem = html_path.stem

    for asset_type, content, attrs in parser.extractions:
        content_hash = compute_content_hash(content)

        if asset_type == "css":
            target_dir = css_dir
            extension = ".css"
            base_name = f"{html_stem}_{content_hash}"
            rel_path = rel_assets_path / CSS_SUBDIR
            css_count += 1

        else:  # js
            target_dir = js_dir
            extension = ".js"
            base_name = f"{html_stem}_{content_hash}"
            rel_path = rel_assets_path / JS_SUBDIR
            js_count += 1

        # Generate unique filename
        filename = get_unique_filename(base_name, extension, target_dir)
        asset_file = target_dir / filename

        # Write asset file
        try:
            asset_file.write_text(content, encoding="utf-8")
        except Exception:
            # Skip this extraction on write failure
            if asset_type == "css":
                css_count -= 1
            else:
                js_count -= 1
            continue

        # Build replacement tag
        rel_path = rel_path / filename
        # Normalize path separators for HTML
        href = str(rel_path).replace("\\", "/")

        if asset_type == "css":
            # Preserve other attributes except the ones we're replacing
            other_attrs = " ".join(
                f'{k}="{v}"' if v else k
                for k, v in attrs.items()
                if k not in ("href", "rel")
            )
            if other_attrs:
                replacement = f'<link rel="stylesheet" href="{href}" {other_attrs}>'
            else:
                replacement = f'<link rel="stylesheet" href="{href}">'
        else:
            # For scripts, preserve non-src attributes
            other_attrs = " ".join(
                f'{k}="{v}"' if v else k for k, v in attrs.items() if k != "src"
            )
            if other_attrs:
                replacement = f'<script src="{href}" {other_attrs}></script>'
            else:
                replacement = f'<script src="{href}"></script>'

        replacements.append((content, replacement))

    # Apply replacements in reverse order to maintain positions
    # (important when content might appear multiple times)
    modified_html = html_content

    for original_content, replacement in replacements:
        # Escape special regex characters in the original content
        # Use a more targeted approach: find the full tag containing this content
        # This is a simplified approach - for production, consider using a proper HTML parser
        escaped_content = re.escape(original_content)

        # Pattern to match the tag with this exact content
        patterns = [
            # Style tag patterns
            rf"(<style[^>]*>)\s*{escaped_content}\s*(</style>)",
            # Script tag patterns
            rf"(<script[^>]*>)\s*{escaped_content}\s*(</script>)",
        ]

        for pattern in patterns:
            try:
                match = re.search(pattern, modified_html, re.DOTALL | re.IGNORECASE)
                if match:
                    # Check if it's a style or script based on the tag
                    if "<style" in match.group(1).lower():
                        modified_html = (
                            modified_html[: match.start()]
                            + replacement
                            + modified_html[match.end() :]
                        )
                    else:
                        modified_html = (
                            modified_html[: match.start()]
                            + replacement
                            + modified_html[match.end() :]
                        )
                    break
            except re.error:
                continue

    return modified_html, css_count, js_count


def process_html_file(path: Path) -> ExtractionResult:
    """
    Process a single HTML file: extract assets and update in place.

    Args:
        path: Path to HTML file

    Returns:
        ExtractionResult with processing status
    """
    try:
        # Read file with size check
        if not path.is_file():
            return ExtractionResult(path=path, success=False, error="Not a file")

        # Check file size (skip extremely large files by default)
        MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
        file_size = path.stat().st_size

        if file_size > MAX_FILE_SIZE:
            return ExtractionResult(
                path=path,
                success=False,
                error=f"File too large ({file_size / 1024 / 1024:.1f} MB)",
            )

        if file_size == 0:
            return ExtractionResult(path=path, success=True, error="Empty file")

        # Read HTML content
        html_content = path.read_text(encoding="utf-8", errors="replace")

        # Create assets directory relative to HTML file
        assets_dir = path.parent / ASSETS_DIR_NAME

        # Extract assets
        modified_html, css_count, js_count = extract_assets_from_html(
            html_content, path, assets_dir
        )

        # Only write back if changes were made
        if css_count > 0 or js_count > 0:
            # Write to temporary file first for atomic operation
            temp_path = path.with_suffix(path.suffix + ".tmp")
            try:
                temp_path.write_text(modified_html, encoding="utf-8")
                temp_path.replace(path)
            except Exception:
                # Clean up temp file on failure
                if temp_path.exists():
                    temp_path.unlink()
                raise

        return ExtractionResult(
            path=path, success=True, css_count=css_count, js_count=js_count
        )

    except UnicodeDecodeError as e:
        return ExtractionResult(path=path, success=False, error=f"Encoding error: {e}")
    except PermissionError as e:
        return ExtractionResult(
            path=path, success=False, error=f"Permission denied: {e}"
        )
    except Exception as e:
        return ExtractionResult(
            path=path, success=False, error=f"{type(e).__name__}: {e}"
        )


def find_html_files(paths: list[Path]) -> Iterator[Path]:
    """
    Find all HTML files from given paths (files and directories).

    Args:
        paths: List of file/directory paths

    Yields:
        Path objects for HTML files
    """
    seen = set()

    for path in paths:
        path = path.resolve()

        if path.is_file():
            if path.suffix.lower() in HTML_EXTENSIONS and path not in seen:
                seen.add(path)
                yield path

        elif path.is_dir():
            for html_file in path.rglob("*"):
                if html_file.is_file() and html_file.suffix.lower() in HTML_EXTENSIONS:
                    resolved = html_file.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        yield resolved

        else:
            print(f"Warning: Path does not exist: {path}", file=sys.stderr)


def get_default_paths() -> list[Path]:
    """Get default paths (current directory) when no input provided."""
    return [Path.cwd()]


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Extract inline CSS and JavaScript from HTML files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s                          # Process current directory recursively
    %(prog)s index.html               # Process single file
    %(prog)s src/ dist/               # Process multiple directories
    %(prog)s *.html                   # Process multiple files (shell glob)
        """,
    )

    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to process (default: current directory)",
    )

    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=NUM_WORKERS,
        help=f"Number of worker processes (default: {NUM_WORKERS})",
    )

    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress progress output"
    )

    parser.add_argument(
        "--min-size",
        type=int,
        default=MIN_INLINE_SIZE,
        help=f"Minimum inline content size to extract (default: {MIN_INLINE_SIZE})",
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_arguments()

    # Update global configuration
    global MIN_INLINE_SIZE
    MIN_INLINE_SIZE = args.min_size

    # Determine paths to process
    paths = args.paths if args.paths else get_default_paths()

    # Find all HTML files
    if not args.quiet:
        print("Scanning for HTML files...", file=sys.stderr)

    html_files = list(find_html_files(paths))

    if not html_files:
        print("No HTML files found.", file=sys.stderr)
        return 0

    if not args.quiet:
        print(f"Found {len(html_files)} HTML file(s) to process.", file=sys.stderr)

    # Process files using multiprocessing
    num_workers = min(args.workers, len(html_files), mp.cpu_count() * 2)
    num_workers = max(1, num_workers)

    if not args.quiet:
        print(f"Using {num_workers} worker(s)...", file=sys.stderr)

    total_css = 0
    total_js = 0
    total_processed = 0
    total_errors = 0

    # Use imap_unordered for better throughput
    with mp.Pool(processes=num_workers) as pool:
        try:
            for result in pool.imap_unordered(
                process_html_file, html_files, chunksize=4
            ):
                total_processed += 1

                if result.success:
                    total_css += result.css_count
                    total_js += result.js_count

                    if not args.quiet:
                        if result.css_count > 0 or result.js_count > 0:
                            print(
                                f"✓ {result.path}: "
                                f"{result.css_count} CSS, {result.js_count} JS extracted",
                                file=sys.stderr,
                            )
                        elif result.error:
                            print(f"○ {result.path}: {result.error}", file=sys.stderr)
                else:
                    total_errors += 1
                    print(f"✗ {result.path}: {result.error}", file=sys.stderr)

        except KeyboardInterrupt:
            print("\nInterrupted by user.", file=sys.stderr)
            pool.terminate()
            return 130

    # Print summary
    print(
        f"\nSummary: {total_processed} file(s) processed, "
        f"{total_css} CSS and {total_js} JS extracted, "
        f"{total_errors} error(s).",
        file=sys.stderr,
    )

    return 1 if total_errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
