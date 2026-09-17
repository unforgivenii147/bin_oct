#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI script that extracts URLs from source files in the
current working directory.

The generated script should:
- Recursively scan the current working directory for regular files, skipping
  common noise directories (".git", "__pycache__", ".venv", "venv",
  "node_modules", ".env", "dist", "build").
- Skip files larger than 10 MiB and files that cannot be decoded.
- Extract URLs using a compiled case-insensitive regex, strip trailing
  punctuation, and classify each URL as a Git host URL (GitHub, GitLab,
  Gitea, Bitbucket, SourceHut, Codeberg, GitBucket, Gogs) or a regular URL.
- Process files concurrently via multiprocessing.Pool.imap_unordered with a
  fixed pool of 8 workers (no CLI flag controls parallelism), showing
  progress with tqdm.
- Write the sorted results to "urls.txt" and "gitlinks.txt" in the current
  directory and log a summary with loguru.
- Include complete type annotations, docstrings on every function, and this
  module-level docstring.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from multiprocessing import Pool
from pathlib import Path
from typing import List, Optional, Set, Tuple

from loguru import logger
from tqdm import tqdm

POOL_SIZE: int = 8
MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024
TRAILING_CHARS: str = ".,;:!?)'\"`"
URLS_FILENAME: str = "urls.txt"
GITLINKS_FILENAME: str = "gitlinks.txt"

EXCLUDE_DIRS: set[str] = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".env",
    "dist",
    "build",
}

URL_PATTERN: re.Pattern[str] = re.compile(
    r'https?://[^\s<>r"{}|\^`\[\]]*', re.IGNORECASE
)

GIT_DOMAINS: set[str] = {
    "github.com",
    "gitlab.com",
    "gitea.io",
    "bitbucket.org",
    "git.sr.ht",
    "codeberg.org",
    "gitbucket.org",
    "gogs.io",
}

UrlPair = tuple[set[str], set[str]]


def is_git_url(url: str) -> bool:
    """Return True if ``url`` points to a known Git hosting domain.

    Args:
        url: URL to classify.

    Returns:
        ``True`` when the URL contains one of the recognized Git domains.
    """
    lowered: str = url.lower()
    domain: str
    for domain in GIT_DOMAINS:
        if domain in lowered:
            return True
    return False


def extract_urls_from_file(file_path: Path) -> UrlPair:
    """Extract regular and Git URLs from a single file.

    Args:
        file_path: Path to the file to scan.

    Returns:
        A tuple ``(regular_urls, git_urls)`` of unique URL strings. Both sets
        are empty for oversized, unreadable, or failing files.
    """
    regular_urls: set[str] = set()
    git_urls: set[str] = set()

    try:
        if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
            return regular_urls, git_urls
        try:
            content: str = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return regular_urls, git_urls

        raw_url: str
        for raw_url in URL_PATTERN.findall(content):
            url: str = raw_url.rstrip(TRAILING_CHARS)
            if not url:
                continue
            if is_git_url(url):
                git_urls.add(url)
            else:
                regular_urls.add(url)
    except Exception:
        pass

    return regular_urls, git_urls


def _collect_files(root: Path) -> list[Path]:
    """Return all regular files under ``root`` outside excluded directories.

    Args:
        root: Directory to scan recursively.

    Returns:
        A list of candidate file paths.
    """
    files: list[Path] = []
    path: Path
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def _write_lines(path: Path, lines: Iterable[str]) -> None:
    """Write ``lines`` to ``path``, one per line.

    Args:
        path: Output file path.
        lines: Iterable of strings to write.
    """
    with path.open("w", encoding="utf-8") as f:
        f.writelines(line + "\n" for line in lines)


def main(argv: Iterable[str] | None = None) -> int:
    """Entry point for the URL extraction script.

    Args:
        argv: Optional argument vector (currently unused; reserved for
            future options).

    Returns:
        Process exit code (0 on success).
    """
    _ = list(argv) if argv is not None else sys.argv[1:]

    current_dir: Path = Path.cwd()
    all_files: list[Path] = _collect_files(current_dir)

    if not all_files:
        logger.info("No files found to process.")
        return 0

    logger.info("Found {} files to process...", len(all_files))

    all_regular_urls: set[str] = set()
    all_git_urls: set[str] = set()

    with Pool(processes=POOL_SIZE) as pool:
        result: UrlPair
        for result in tqdm(
            pool.imap_unordered(extract_urls_from_file, all_files),
            total=len(all_files),
            desc="Processing files",
            unit="file",
        ):
            regular_urls, git_urls = result
            all_regular_urls.update(regular_urls)
            all_git_urls.update(git_urls)

    sorted_regular: list[str] = sorted(all_regular_urls)
    sorted_git: list[str] = sorted(all_git_urls)

    urls_file: Path = current_dir / URLS_FILENAME
    gitlinks_file: Path = current_dir / GITLINKS_FILENAME

    _write_lines(urls_file, sorted_regular)
    _write_lines(gitlinks_file, sorted_git)

    logger.info("Extraction complete!")
    logger.info("  Regular URLs: {} -> {}", len(sorted_regular), urls_file.name)
    logger.info("  Git URLs: {} -> {}", len(sorted_git), gitlinks_file.name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
