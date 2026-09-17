#!/data/data/com.termux/files/home/.local/bin/python
"""
HTML Formatter using Tree-sitter
Formats HTML files so every tag starts on a new line.
"""

import logging
import multiprocessing as mp
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

try:
    import tree_sitter_html as ts_html
    from tree_sitter import Language, Node, Parser
except ImportError:
    print("Error: Required packages not installed.", file=sys.stderr)
    print("Install with: pip install tree-sitter tree-sitter-html", file=sys.stderr)
    sys.exit(1)


# Configuration
HTML_EXTENSIONS = {".html", ".htm", ".xhtml"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB limit for safety
WORKERS = 8
CHUNK_SIZE = 1024 * 1024  # 1MB chunks for reading

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Result of processing a single file."""

    path: Path
    success: bool
    error: str | None = None
    bytes_processed: int = 0
    tags_formatted: int = 0
    was_modified: bool = False


class HTMLFormatter:
    """HTML formatter using Tree-sitter parser."""

    # Tags that should be on their own line
    BLOCK_TAGS = {
        "html",
        "head",
        "body",
        "div",
        "p",
        "span",
        "section",
        "article",
        "header",
        "footer",
        "nav",
        "aside",
        "main",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "li",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "tr",
        "td",
        "th",
        "form",
        "input",
        "button",
        "select",
        "option",
        "textarea",
        "label",
        "fieldset",
        "legend",
        "script",
        "style",
        "link",
        "meta",
        "title",
        "br",
        "hr",
        "img",
        "a",
        "iframe",
        "video",
        "audio",
        "source",
        "canvas",
        "svg",
        "template",
        "slot",
        "custom-element",
    }

    # Tags that should stay inline (typically text-only)
    INLINE_TAGS = {"b", "i", "u", "em", "strong", "code", "small", "sub", "sup"}

    def __init__(self):
        """Initialize the formatter with Tree-sitter HTML parser."""
        try:
            self.HTML_LANGUAGE = Language(ts_html.language())
            self.parser = Parser(self.HTML_LANGUAGE)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Tree-sitter parser: {e}")

    def format_html(self, source_code: str) -> tuple[str, int]:
        """
        Format HTML source code so every tag starts on a new line.

        Args:
            source_code: The HTML source code as a string

        Returns:
            Tuple of (formatted_code, number_of_tags_formatted)
        """
        if not source_code.strip():
            return source_code, 0

        try:
            # Parse the HTML
            tree = self.parser.parse(bytes(source_code, "utf8"))

            # Extract formatting information
            edits = self._collect_edits(tree.root_node, source_code)

            if not edits:
                return source_code, 0

            # Apply edits in reverse order to maintain position validity
            edits.sort(key=lambda x: x[0], reverse=True)
            result = source_code

            for pos, insert_text, delete_count in edits:
                result = result[:pos] + insert_text + result[pos + delete_count :]

            # Clean up excessive blank lines
            result = self._cleanup_blank_lines(result)

            return result, len(edits)

        except Exception as e:
            logger.error(f"Error formatting HTML: {e}")
            return source_code, 0

    def _collect_edits(self, node: Node, source: str) -> list[tuple[int, str, int]]:
        """
        Collect all edit operations needed for formatting.

        Returns list of (position, insert_text, delete_count) tuples.
        """
        edits = []

        # Walk the tree iteratively for better performance
        stack = [node]
        last_end = 0

        while stack:
            current = stack.pop()

            # Process element nodes
            if current.type == "element":
                # Get tag name
                tag_name = self._get_tag_name(current, source)

                if tag_name and self._should_format_tag(tag_name):
                    start_byte = current.start_byte
                    end_byte = current.end_byte

                    # Check if there's content before this tag on the same line
                    line_start = source.rfind("\n", 0, start_byte) + 1
                    prefix = source[line_start:start_byte]

                    # Add newline before tag if needed
                    if prefix.strip() and not prefix.strip().endswith("\n"):
                        edits.append((start_byte, "\n", 0))

                    # Check if there's content after the closing tag on the same line
                    next_newline = source.find("\n", end_byte)
                    if next_newline == -1:
                        next_newline = len(source)

                    suffix = source[end_byte:next_newline]
                    if suffix.strip():
                        edits.append((end_byte, "\n", 0))

            # Add children to stack (reverse order for left-to-right processing)
            for child in reversed(current.children):
                stack.append(child)

        return edits

    def _get_tag_name(self, element_node: Node, source: str) -> str | None:
        """Extract tag name from an element node."""
        for child in element_node.children:
            if child.type == "start_tag":
                for tag_child in child.children:
                    if tag_child.type == "tag_name":
                        return source[tag_child.start_byte : tag_child.end_byte].lower()
        return None

    def _should_format_tag(self, tag_name: str) -> bool:
        """Determine if a tag should be formatted on its own line."""
        # Format all tags except explicit inline tags
        return tag_name not in self.INLINE_TAGS

    def _cleanup_blank_lines(self, text: str) -> str:
        """Remove excessive blank lines (more than 2 consecutive)."""
        lines = text.split("\n")
        result = []
        blank_count = 0

        for line in lines:
            if line.strip():
                blank_count = 0
                result.append(line)
            else:
                blank_count += 1
                if blank_count <= 1:  # Allow maximum 1 consecutive blank line
                    result.append(line)

        return "\n".join(result)


def read_file_safe(path: Path, max_size: int = MAX_FILE_SIZE) -> str | None:
    """
    Safely read a file with size limit and encoding detection.

    Returns file content as string or None if failed.
    """
    try:
        # Check file size
        file_size = path.stat().st_size
        if file_size > max_size:
            logger.warning(f"File too large ({file_size} bytes): {path}")
            return None

        # Try UTF-8 first, then fallback to latin-1
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            logger.debug(f"UTF-8 decode failed, trying latin-1: {path}")
            content = path.read_text(encoding="latin-1")

        return content

    except OSError as e:
        logger.error(f"Failed to read {path}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error reading {path}: {e}")
        return None


def write_file_atomic(path: Path, content: str) -> bool:
    """
    Write file atomically using a temporary file.

    Returns True if successful, False otherwise.
    """
    temp_path = path.with_suffix(path.suffix + ".tmp")

    try:
        # Write to temporary file
        temp_path.write_text(content, encoding="utf-8")

        # Atomic rename
        temp_path.replace(path)
        return True

    except Exception as e:
        logger.error(f"Failed to write {path}: {e}")
        # Clean up temp file if it exists
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass
        return False


def find_html_files(paths: list[Path]) -> Iterator[Path]:
    """
    Find all HTML files in the given paths.

    If paths is empty, searches current directory recursively.
    """
    if not paths:
        paths = [Path.cwd()]

    seen = set()  # Avoid duplicates

    for path in paths:
        try:
            if path.is_file():
                # Single file
                if path.suffix.lower() in HTML_EXTENSIONS and path not in seen:
                    seen.add(path)
                    yield path
            elif path.is_dir():
                # Directory - search recursively
                for html_file in path.rglob("*"):
                    if (
                        html_file.is_file()
                        and html_file.suffix.lower() in HTML_EXTENSIONS
                        and html_file not in seen
                    ):
                        seen.add(html_file)
                        yield html_file
            else:
                logger.warning(f"Path does not exist: {path}")

        except (OSError, PermissionError) as e:
            logger.error(f"Error accessing {path}: {e}")
            continue


def process_file(path: Path) -> ProcessingResult:
    """
    Process a single HTML file.

    Returns ProcessingResult with status information.
    """
    try:
        # Read file
        content = read_file_safe(path)
        if content is None:
            return ProcessingResult(
                path=path, success=False, error="Failed to read file"
            )

        # Format HTML
        formatter = HTMLFormatter()
        formatted, tag_count = formatter.format_html(content)

        # Check if file was modified
        was_modified = formatted != content

        # Write back if modified
        if was_modified and not write_file_atomic(path, formatted):
            return ProcessingResult(
                path=path,
                success=False,
                error="Failed to write file",
                bytes_processed=len(content),
                tags_formatted=tag_count,
            )

        return ProcessingResult(
            path=path,
            success=True,
            bytes_processed=len(content),
            tags_formatted=tag_count,
            was_modified=was_modified,
        )

    except Exception as e:
        logger.error(f"Unexpected error processing {path}: {e}")
        return ProcessingResult(path=path, success=False, error=str(e))


def main() -> int:
    """Main entry point."""
    # Parse command line arguments
    import argparse

    parser = argparse.ArgumentParser(
        description="Format HTML files so every tag starts on a new line",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Process current directory recursively
  %(prog)s file.html          # Process single file
  %(prog)s dir1/ dir2/        # Process multiple directories
  %(prog)s *.html             # Process all HTML files in current dir
        """,
    )

    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to process (default: current directory)",
    )

    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=WORKERS,
        help=f"Number of parallel workers (default: {WORKERS})",
    )

    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without modifying files",
    )

    args = parser.parse_args()

    # Configure logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Find all HTML files
    print("Searching for HTML files...")
    html_files = list(find_html_files(args.paths))

    if not html_files:
        logger.warning("No HTML files found")
        return 0

    print(f"Found {len(html_files)} HTML file(s)")

    if args.dry_run:
        for f in html_files:
            print(f"Would process: {f}")
        return 0

    # Process files in parallel
    success_count = 0
    failed_count = 0
    modified_count = 0
    total_bytes = 0
    total_tags = 0

    try:
        with mp.Pool(processes=args.jobs) as pool:
            # Process files with imap_unordered for better performance
            for result in pool.imap_unordered(process_file, html_files, chunksize=1):
                if result.success:
                    success_count += 1
                    total_bytes += result.bytes_processed
                    total_tags += result.tags_formatted

                    if result.was_modified:
                        modified_count += 1
                        print(f"✓ Formatted: {result.path}")
                    else:
                        logger.debug(f"✓ Already formatted: {result.path}")
                else:
                    failed_count += 1
                    logger.error(f"✗ Failed: {result.path} - {result.error}")

    except KeyboardInterrupt:
        logger.warning("\nInterrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1

    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Files processed:  {success_count + failed_count}")
    print(f"  Successful:     {success_count}")
    print(f"  Failed:         {failed_count}")
    print(f"  Modified:       {modified_count}")
    print(f"  Unchanged:      {success_count - modified_count}")
    print(f"Total tags formatted: {total_tags}")
    print(f"Total bytes processed: {total_bytes:,}")

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
