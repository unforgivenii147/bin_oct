#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that recursively scans a directory for files, extracts
HTTP/FTP/HTTPS URLs and GitHub repository URLs from text-like files, PDFs, and
common archive formats (tar.gz, tar.xz, zip, whl), and writes the unique results
to "urls" and "giturls". Use multiprocessing.Pool.apply_async with a fixed pool
of 8 workers, loguru for logging, pathlib for paths, chardet for encoding
detection, and include full type hints and docstrings.
"""

from __future__ import annotations

import re
import tarfile
import zipfile
from multiprocessing import Pool
from pathlib import Path

import chardet
from loguru import logger

TARGET_EXTENSIONS: set[str] = {
    ".tar.gz",
    ".pdf",
    ".zip",
    ".css",
    ".js",
    ".tar.xz",
    ".7z",
    ".whl",
    ".html",
}

COMPRESSED_ARCHIVES: set[str] = {
    ".tar.xz",
    ".tar.gz",
    ".tar.zst",
    ".7z",
    ".br",
    ".zip",
    ".whl",
}

GITHUB_REPO_REGEX: re.Pattern[str] = re.compile(
    r"https?://(?:www\.)?github\.com/[a-zA-Z0-9\-]+/[a-zA-Z0-9\-]+"
)

URL_REGEX: re.Pattern[str] = re.compile(
    r"(http|ftp|https)://([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:/~+#-]*[\w@?^=%&/~+#-])?"
)

MAX_WORKERS: int = 8


def extract_links_from_text(text: str, path: Path | str) -> tuple[list[str], list[str]]:
    """Extract generic URLs and GitHub repository URLs from a text blob.

    Args:
        text: The text content to scan for URLs.
        path: The originating file path (used for logging/debugging context).

    Returns:
        A tuple of (generic_urls, github_urls).
    """
    urls: list[str] = URL_REGEX.findall(text)
    github_urls: list[str] = GITHUB_REPO_REGEX.findall(text)
    return urls, github_urls


def read_file_with_encodings(
    path: Path,
) -> tuple[str | None, str | None]:
    """Read a file trying a sequence of common encodings, then chardet fallback.

    Args:
        path: Path to the file to read.

    Returns:
        A tuple (content, encoding). Content is None if reading fails.
        Encoding is None if content was read with an explicit encoding or
        reading failed entirely.
    """
    encodings_to_try: list[str] = ["utf-8", "latin-1", "iso-8859-1", "cp1252"]
    for encoding in encodings_to_try:
        try:
            content: str = path.read_text(encoding=encoding)
            logger.debug(f"Successfully read {path} with {encoding}")
            return content, None
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.warning(f"Error reading {path} with {encoding}: {e}")
            continue

    try:
        raw_data: bytes = path.read_bytes()
        result: dict[str, object] = chardet.detect(raw_data)
        detected_encoding_obj: object = result.get("encoding")
        detected_encoding: str | None = (
            detected_encoding_obj if isinstance(detected_encoding_obj, str) else None
        )
        if detected_encoding:
            try:
                content = raw_data.decode(detected_encoding)
                logger.debug(
                    f"Successfully read {path} with detected encoding {detected_encoding}"
                )
                return content, detected_encoding
            except Exception as e:
                logger.warning(
                    f"Error decoding {path} with detected encoding {detected_encoding}: {e}"
                )
    except Exception as e:
        logger.error(f"Failed to read or detect encoding for {path}: {e}")

    return None, None


def _process_tar_archive(path: Path) -> tuple[list[str], list[str]]:
    """Extract URLs from all members of a tar archive.

    Args:
        path: Path to the tar archive.

    Returns:
        A tuple of (local_urls, github_urls).
    """
    local_urls: list[str] = []
    github_urls: list[str] = []
    try:
        with tarfile.open(path, "r:*") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                try:
                    f = tar.extractfile(member)
                    if f is None:
                        continue
                    member_content_bytes: bytes = f.read()
                    result: dict[str, object] = chardet.detect(member_content_bytes)
                    enc_obj: object = result.get("encoding")
                    enc: str = (
                        enc_obj if isinstance(enc_obj, str) and enc_obj else "utf-8"
                    )
                    member_content_str: str = member_content_bytes.decode(
                        enc, errors="ignore"
                    )
                    if member_content_str:
                        urls, gh_urls = extract_links_from_text(
                            member_content_str, f"{path}/{member.name}"
                        )
                        local_urls.extend(urls)
                        github_urls.extend(gh_urls)
                except Exception as e:
                    logger.warning(
                        f"Error processing member {member.name} in {path}: {e}"
                    )
        logger.debug(f"Extracted from Tar archive: {path}")
    except Exception as e:
        logger.error(f"Unexpected error processing tar archive {path}: {e}")
    return local_urls, github_urls


def _process_zip_archive(path: Path) -> tuple[list[str], list[str]]:
    """Extract URLs from all members of a zip/whl archive.

    Args:
        path: Path to the zip or whl archive.

    Returns:
        A tuple of (local_urls, github_urls).
    """
    local_urls: list[str] = []
    github_urls: list[str] = []
    try:
        with zipfile.ZipFile(path, "r") as zip_ref:
            for file_info in zip_ref.infolist():
                if file_info.is_dir():
                    continue
                with zip_ref.open(file_info) as f:
                    member_content_bytes: bytes = f.read()
                    result: dict[str, object] = chardet.detect(member_content_bytes)
                    enc_obj: object = result.get("encoding")
                    enc: str = (
                        enc_obj if isinstance(enc_obj, str) and enc_obj else "utf-8"
                    )
                    member_content_str: str = member_content_bytes.decode(
                        enc, errors="ignore"
                    )
                    if member_content_str:
                        urls, gh_urls = extract_links_from_text(
                            member_content_str, f"{path}/{file_info.filename}"
                        )
                        local_urls.extend(urls)
                        github_urls.extend(gh_urls)
        logger.debug(f"Extracted from ZIP archive: {path}")
    except Exception as e:
        logger.error(f"Unexpected error processing zip archive {path}: {e}")
    return local_urls, github_urls


def _process_7z_archive(path: Path) -> tuple[list[str], list[str]]:
    """Handle 7z archives without a dedicated extractor.

    Currently treats the file as binary and attempts text extraction, since
    py7zr is not a dependency.

    Args:
        path: Path to the 7z archive.

    Returns:
        A tuple of (local_urls, github_urls).
    """
    local_urls: list[str] = []
    github_urls: list[str]
