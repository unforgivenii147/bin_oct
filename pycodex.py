#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that extracts Python code blocks from HTML files or URLs.

The script should:
- Accept CLI arguments for a single HTML file (-f/--file), a directory of HTML files (-p/--path), or a URL (-u/--url), plus an output directory (-o/--output, default ./output).
- Recursively discover *.html files when scanning a directory (or the current directory by default).
- Parse HTML using BeautifulSoup, extracting Python code from <pre><code>, standalone <code>, and JSON-containing <script> tags.
- Detect Python code heuristically using keyword and regex pattern matching.
- Support optional filename hints inside code comments (e.g. "# filename: foo.py").
- Save each extracted block as a .py file under output/<source_name>/, avoiding filename collisions.
- Use multiprocessing.Pool.apply_async with a fixed pool of 8 workers for parallel processing.
- Use loguru for all logging (no print(statements, no stdlib logging).)
- Use pathlib exclusively for filesystem operations.
- Include complete type annotations on all functions, methods, attributes, and module-level variables.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Any, Final

import requests
from bs4 import BeautifulSoup
from loguru import logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

PYTHON_KEYWORDS: Final[tuple[str, ...]] = (
    "def ",
    "class ",
    "import ",
    "from ",
    "if ",
    "for ",
    "while ",
    "try:",
    "except",
    "with ",
    "lambda",
    "return ",
    "yield ",
    "async ",
    "await ",
    "@",
    "elif ",
    "else:",
    "self.",
)

PYTHON_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bdef\s+\w+\s*\(",
        r"\bclass\s+\w+",
        r"\bif\s+.*:",
        r"\bfor\s+.*\s+in\s+",
        r"\bimport\s+",
        r"\breturn\s+",
        r"\b(True|False|None)\b",
    )
)

FILENAME_HINT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"#\s*(?:filename|name|file)\s*:?\s*([\w\-._]+\.py)",
    re.IGNORECASE,
)

JSON_CODE_KEYWORDS: Final[tuple[str, ...]] = (
    "def ",
    "import ",
    "class ",
    "if __name__",
)

DEFAULT_OUTPUT_DIR: Final[str] = "./output"
POOL_SIZE: Final[int] = 8
MAX_JSON_DEPTH: Final[int] = 5


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CodeBlock:
    """A single extracted Python code block and its provenance."""

    content: str
    language: str
    source_file: str
    block_index: int
    suggested_name: str | None = None


# ---------------------------------------------------------------------------
# HTTP session helper
# ---------------------------------------------------------------------------


class HTTPSession:
    """Wrapper around requests.Session with retry logic and a fixed timeout."""

    def __init__(self, max_retries: int = 3, timeout: int = 10) -> None:
        """Initialize the HTTP session with retry strategy and timeout."""
        self.session: requests.Session = requests.Session()
        retry_strategy: Retry = Retry(total=max_retries, backoff_factor=1)
        adapter: HTTPAdapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.timeout: int = timeout

    def fetch(self, url: str) -> str | None:
        """Fetch the given URL, returning its text or None on failure."""
        try:
            response: requests.Response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            logger.exception("Failed to fetch {}: {}", url, exc)
            return None

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()


# ---------------------------------------------------------------------------
# Code block extractor
# ---------------------------------------------------------------------------


class CodeBlockExtractor:
    """Extracts Python code blocks from HTML content."""

    def __init__(self) -> None:
        """Create the extractor with its own HTTP session."""
        self.http_session: HTTPSession = HTTPSession()

    def extract_from_html(self, html_content: str, source_file: str) -> list[CodeBlock]:
        """Extract all Python code blocks from the given HTML content."""
        soup: BeautifulSoup = BeautifulSoup(html_content, "html.parser")
        code_blocks: list[CodeBlock] = []
        code_blocks.extend(self._extract_from_pre_code(soup, source_file))
        code_blocks.extend(self._extract_from_code_tags(soup, source_file))
        code_blocks.extend(self._extract_from_canvas(soup, source_file))
        return code_blocks

    def _extract_from_pre_code(
        self, soup: BeautifulSoup, source_file: str
    ) -> list[CodeBlock]:
        """Extract Python code from <pre><code> blocks."""
        blocks: list[CodeBlock] = []
        for idx, pre in enumerate(soup.find_all("pre")):
            code = pre.find("code")
            if code is not None:
                content: str = code.get_text()
                if self._is_python_code(content):
                    block: CodeBlock = CodeBlock(
                        content=content,
                        language="python",
                        source_file=source_file,
                        block_index=idx,
                        suggested_name=self._extract_filename_from_code(content),
                    )
                    blocks.append(block)
        return blocks

    def _extract_from_code_tags(
        self, soup: BeautifulSoup, source_file: str
    ) -> list[CodeBlock]:
        """Extract Python code from standalone <code> tags (not inside <pre>)."""
        blocks: list[CodeBlock] = []
        offset: int = len(soup.find_all("pre"))
        for idx, code in enumerate(soup.find_all("code")):
            parent = code.parent
            if parent is not None and getattr(parent, "name", None) == "pre":
                continue
            content: str = code.get_text()
            if self._is_python_code(content):
                block: CodeBlock = CodeBlock(
                    content=content,
                    language="python",
                    source_file=source_file,
                    block_index=offset + idx,
                    suggested_name=self._extract_filename_from_code(content),
                )
                blocks.append(block)
        return blocks

    def _extract_from_canvas(
        self, soup: BeautifulSoup, source_file: str
    ) -> list[CodeBlock]:
        """Extract Python code embedded in JSON <script> tags."""
        blocks: list[CodeBlock] = []
        offset: int = len(soup.find_all("pre")) + len(soup.find_all("code"))
        for idx, script in enumerate(soup.find_all("script")):
            script_type = script.get("type")
            script_id = str(script.get("id", "")).lower()
            if script_type == "application/json" or "canvas" in script_id:
                try:
                    content: str | None = script.string
                    if content:
                        data: Any = json.loads(content)
                        python_codes: list[str] = self._extract_from_json(data)
                        for py_code in python_codes:
                            if self._is_python_code(py_code):
                                block: CodeBlock = CodeBlock(
                                    content=py_code,
                                    language="python",
                                    source_file=source_file,
                                    block_index=offset + idx,
                                    suggested_name=self._extract_filename_from_code(
                                        py_code
                                    ),
                                )
                                blocks.append(block)
                except (json.JSONDecodeError, TypeError):
                    pass
        return blocks

    def _extract_from_json(
        self, data: Any, depth: int = 0, max_depth: int = MAX_JSON_DEPTH
    ) -> list[str]:
        """Recursively walk JSON data, collecting strings that look like Python."""
        if depth > max_depth:
            return []
        python_codes: list[str] = []
        if isinstance(data, dict):
            for value in data.values():
                python_codes.extend(
                    self._extract_from_json(value, depth + 1, max_depth)
                )
        elif isinstance(data, list):
            for item in data:
                python_codes.extend(self._extract_from_json(item, depth + 1, max_depth))
        elif isinstance(data, str) and any(
            keyword in data for keyword in JSON_CODE_KEYWORDS
        ):
            python_codes.append(data)
        return python_codes

    def _is_python_code(self, content: str) -> bool:
        """Heuristically determine whether content looks like Python code."""
        if not content.strip():
            return False
        content_lower: str = content.lower()
        keyword_count: int = sum(
            1 for keyword in PYTHON_KEYWORDS if keyword.lower() in content_lower
        )
        pattern_matches: int = sum(
            1 for pattern in PYTHON_PATTERNS if pattern.search(content)
        )
        return keyword_count >= 2 or pattern_matches >= 2

    def _extract_filename_from_code(self, content: str) -> str | None:
        """Look for a filename hint comment within the first 10 lines of code."""
        lines: list[str] = content.split("\n")
        for line in lines[:10]:
            match: re.Match[str] | None = FILENAME_HINT_PATTERN.search(line)
            if match is not None:
                return match.group(1)
        return None

    def close(self) -> None:
        """Close the extractor's HTTP session."""
        self.http_session.close()


# ---------------------------------------------------------------------------
# File processor
# ---------------------------------------------------------------------------


class FileProcessor:
    """Extracts code blocks from files/URLs and persists them to disk."""

    def __init__(self, output_dir: str = DEFAULT_OUTPUT_DIR) -> None:
        """Initialize the processor with the given output directory."""
        self.output_dir: Path = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.extractor: CodeBlockExtractor = CodeBlockExtractor()

    def process_file(self, path: str) -> int:
        """Extract code blocks from a single HTML file. Returns the count."""
        try:
            path: Path = Path(path)
            if path.suffix.lower() != ".html":
                return 0
            html_content: str = path.read_text(encoding="utf-8", errors="ignore")
            code_blocks: list[CodeBlock] = self.extractor.extract_from_html(
                html_content, str(path)
            )
            if code_blocks:
                self._save_code_blocks(code_blocks, str(path))
                print("Extracted {} code blocks from {}", len(code_blocks), path)
            return len(code_blocks)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error processing {}: {}", path, exc)
            return 0

    def process_url(self, url: str) -> int:
        """Extract code blocks from a URL. Returns the count."""
        try:
            html_content: str | None = self.extractor.http_session.fetch(url)
            if not html_content:
                return 0
            code_blocks: list[CodeBlock] = self.extractor.extract_from_html(
                html_content, url
            )
            if code_blocks:
                self._save_code_blocks(code_blocks, url)
                print("Extracted {} code blocks from {}", len(code_blocks), url)
            return len(code_blocks)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error processing URL {}: {}", url, exc)
            return 0

    def _save_code_blocks(self, code_blocks: list[CodeBlock], source: str) -> None:
        """Persist code blocks to disk under output/<source_name>/."""
        source_name: str
        if source.startswith("http"):
            source_name = "url_content"
        else:
            source_name = Path(source).stem

        source_dir: Path = self.output_dir / source_name
        source_dir.mkdir(parents=True, exist_ok=True)

        for block in code_blocks:
            filename: str = (
                block.suggested_name
                or f"{source_name}_block_{block.block_index:03d}.py"
            )
            path: Path = source_dir / filename
            counter: int = 1
            original_path: Path = path
            while path.exists():
                name_parts: list[str] = original_path.stem.rsplit("_", 1)
                if len(name_parts) == 2 and name_parts[1].isdigit():
                    base_name: str = name_parts[0]
                else:
                    base_name = original_path.stem
                path = source_dir / f"{base_name}_{counter}.py"
                counter += 1
            path.write_text(block.content, encoding="utf-8")
            logger.debug("Saved code block to {}", path)

    def close(self) -> None:
        """Release resources held by the underlying extractor."""
        self.extractor.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def find_html_files(directory: str) -> list[str]:
    """Recursively find all .html files under the given directory."""
    path: Path = Path(directory)
    return [str(html_file) for html_file in path.rglob("*.html")]


def _process_file_worker(args: tuple[str, str]) -> int:
    """Worker function for multiprocessing: process a single file."""
    path, output_dir = args
    processor: FileProcessor = FileProcessor(output_dir=output_dir)
    try:
        return processor.process_file(path)
    finally:
        processor.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Extract Python code blocks from HTML files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python script.py -f document.html\n"
            "  python script.py -p /path/to/documents\n"
            "  python script.py -u https://example.com/page.html\n"
            "  python script.py\n"
        ),
    )
    parser.add_argument("-f", "--file", type=str, help="Path to a single HTML file")
    parser.add_argument(
        "-p",
        "--path",
        type=str,
        help="Path to directory containing HTML files",
    )
    parser.add_argument("-u", "--url", type=str, help="URL to fetch HTML content from")
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=DEFAULT_OUTPUT_DIR,
        help=(
            "Output directory for extracted code blocks "
            f"(default: {DEFAULT_OUTPUT_DIR})"
        ),
    )
    return parser


def _process_directory(path: str, output_dir: str) -> int:
    """Process all HTML files in a directory using a fixed multiprocessing pool."""
    html_files: list[str] = find_html_files(path)
    if not html_files:
        logger.warning("No HTML files found in {}", path)
        return 0

    print("Found {} HTML files", len(html_files))
    total_blocks: int = 0
    pool: Pool = Pool(processes=POOL_SIZE)
    try:
        results: list[AsyncResult[int]] = [
            pool.apply_async(_process_file_worker, ((path, output_dir),))
            for path in html_files
        ]
        pool.close()
        for result in results:
            try:
                total_blocks += result.get()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Worker failed: {}", exc)
        pool.join()
    except Exception:
        pool.terminate()
        raise
    return total_blocks


def main() -> int:
    """Parse CLI arguments and run the extraction workflow."""
    parser: argparse.ArgumentParser = _build_parser()
    args: argparse.Namespace = parser.parse_args()

    total_blocks: int = 0

    if args.url:
        print("Processing URL: {}", args.url)
        processor: FileProcessor = FileProcessor(output_dir=args.output)
        try:
            total_blocks += processor.process_url(args.url)
        finally:
            processor.close()
    elif args.file:
        print("Processing file: {}", args.file)
        processor = FileProcessor(output_dir=args.output)
        try:
            total_blocks += processor.process_file(args.file)
        finally:
            processor.close()
    elif args.path:
        print("Processing directory: {}", args.path)
        total_blocks += _process_directory(args.path, args.output)
    else:
        print("Processing HTML files in current directory recursively")
        total_blocks += _process_directory(".", args.output)

    print("Total code blocks extracted: {}", total_blocks)
    print("Results saved to: {}", Path(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
