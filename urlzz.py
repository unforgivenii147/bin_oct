#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that recursively scans files and archives (zip, whl, tar*, 7z, plain text)
in the current working directory (or provided paths), extracts all HTTP/HTTPS URLs using a robust
regex (including GitHub URLs), writes GitHub URLs to /sdcard/data/gitlinks.txt and all unique URLs
to /sdcard/data/urlzz.txt. Use multiprocessing.Pool.apply_async with a fixed pool of 8 workers,
loguru for logging, pathlib for path handling, complete type annotations, and docstrings on all
functions and classes.
"""

from __future__ import annotations

import re
import sys
import tarfile
import zipfile
from collections.abc import Iterable
from multiprocessing import Pool
from pathlib import Path

import py7zr
from dh import cprint, get_nobinary
from loguru import logger

CHUNK_SIZE: int = 1024 * 1024
POOL_SIZE: int = 8
URL_PATTERN: re.Pattern[str] = re.compile(
    r"""https?://[^\s"'<>\)\]\}]+""",
    re.IGNORECASE,
)
GITHUB_PATTERN: re.Pattern[str] = re.compile(
    r"""https?://(?:www\.)?github\.com/[^\s"'<>\)\]\}]+""",
    re.IGNORECASE,
)
ARCHIVE_SUFFIXES_ZIP: set[str] = {".zip", ".whl"}
ARCHIVE_SUFFIXES_TAR: set[str] = {
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.xz",
    ".txz",
    ".tar.zst",
    ".tar.7z",
    ".tar.bz2",
    ".tbz",
    ".tbz2",
}
ARCHIVE_SUFFIXES_7Z: set[str] = {".7z"}
OUTPUT_ALL: Path = Path("/sdcard/data/urlzz.txt")
OUTPUT_GIT: Path = Path("/sdcard/data/gitlinks.txt")


def extract_urls_from_text(content: str) -> set[str]:
    """Extract all HTTP/HTTPS URLs from a text blob."""
    result: set[str] = set(URL_PATTERN.findall(content))
    cprint(result)
    return result


def extract_urls_from_file(path: Path) -> set[str]:
    """Extract URLs from a plain text file."""
    urls: set[str] = set()
    try:
        content: str = path.read_text(encoding="utf-8", errors="ignore")
        urls.update(extract_urls_from_text(content))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to read {path}: {exc}")
    return urls


def extract_urls_from_tar(path: Path) -> set[str]:
    """Extract URLs from a tar archive (any compression)."""
    urls: set[str] = set()
    try:
        with tarfile.open(path, mode="r:*") as tar:
            member: tarfile.TarInfo
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                fileobj = tar.extractfile(member)
                if fileobj is None:
                    continue
                content: str = fileobj.read().decode("utf-8", errors="ignore")
                urls.update(extract_urls_from_text(content))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to read tar {path}: {exc}")
    return urls


def extract_urls_from_zip(path: Path) -> set[str]:
    """Extract URLs from a zip archive (including wheels)."""
    urls: set[str] = set()
    try:
        with zipfile.ZipFile(path, "r") as zf:
            name: str
            for name in zf.namelist():
                try:
                    with zf.open(name) as f:
                        content: str = f.read().decode("utf-8", errors="ignore")
                        urls.update(extract_urls_from_text(content))
                except Exception:  # noqa: BLE001
                    continue
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to read zip {path}: {exc}")
    return urls


def extract_urls_from_7z(path: Path) -> set[str]:
    """Extract URLs from a 7z archive."""
    urls: set[str] = set()
    try:
        with py7zr.SevenZipFile(path, mode="r") as archive:
            all_files = archive.readall()
            bio: object
            for bio in all_files.values():
                try:
                    content: str = bio.read().decode("utf-8", errors="ignore")  # type: ignore[attr-defined]
                    urls.update(extract_urls_from_text(content))
                except Exception:  # noqa: BLE001
                    continue
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to read 7z {path}: {exc}")
    return urls


def extract_urls(path: Path) -> set[str]:
    """Dispatch URL extraction based on the file suffix."""
    suffix: str = path.suffix.lower()
    name: str = path.name.lower()
    if suffix in ARCHIVE_SUFFIXES_ZIP:
        return extract_urls_from_zip(path)
    if suffix in ARCHIVE_SUFFIXES_7Z:
        return extract_urls_from_7z(path)
    if suffix in ARCHIVE_SUFFIXES_TAR or any(
        name.endswith(s) for s in ARCHIVE_SUFFIXES_TAR
    ):
        return extract_urls_from_tar(path)
    return extract_urls_from_file(path)


def _worker(path: Path) -> set[str]:
    """Multiprocessing worker wrapper around :func:`extract_urls`."""
    return extract_urls(path)


def main() -> None:
    """Entry point: scan paths in parallel and write URL outputs."""
    cwd: Path = Path.cwd()
    args: list[str] = sys.argv[1:]
    paths: Iterable[Path] = [Path(p) for p in args] if args else list(get_nobinary(cwd))
    paths: list[Path] = list(paths)

    all_urls: set[str] = set()
    with Pool(processes=POOL_SIZE) as pool:
        async_results = [pool.apply_async(_worker, (path,)) for path in paths]
        result = None
        for result in async_results:
            try:
                all_urls.update(result.get())
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Worker failed: {exc}")

    github_urls: set[str] = {u for u in all_urls if GITHUB_PATTERN.match(u)}

    OUTPUT_ALL.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_ALL.open("a", encoding="utf-8") as f:
        f.write("\n")
        f.writelines(url + "\n" for url in sorted(all_urls))

    with OUTPUT_GIT.open("a", encoding="utf-8") as f:
        f.write("\n")
        f.writelines(url + "\n" for url in sorted(github_urls))

    print(f"Extracted {len(all_urls)} unique URLs to {OUTPUT_ALL}")
    print(f"Extracted {len(github_urls)} GitHub URLs to {OUTPUT_GIT}")


if __name__ == "__main__":
    main()
