#!/data/data/com.termux/files/home/.local/bin/python
"""
pkgfetch.py - Resolve and download Python packages from PEP 503/691 indexes.

Features:
- Resolves PEP 508 requirements from PyPI-compatible simple indexes.
- Falls back to Tsinghua and Yandex mirrors when PyPI/index mirrors fail.
- Prefers source archives (.tar.gz first) over wheels by default.
- Supports .tar.gz, .tar.bz2, .tar.bz, .zip, and other common PyPI archives.
- Supports download backends: httpx, requests, pycurl, aria2c.
- Verifies repository-provided hashes (when published by the index).
- Verifies archive readability after downloading.
- Uses chunked/ranged HTTP downloading for files above 5 MiB where supported.
- Uses loguru for logging.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
from loguru import logger
from packaging.requirements import Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.tags import (
    Tag,
    compatible_tags,
    cpython_tags,
    generic_tags,
    interpreter_name,
    interpreter_version,
)
from packaging.utils import (
    InvalidWheelFilename,
    canonicalize_name,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version


__all__ = [
    "Link",
    "Package",
    "TargetPython",
    "PackageFinder",
    "download",
    "main",
]


PYPI_SIMPLE_URL = "https://pypi.org/simple/"
TSINGHUA_SIMPLE_URL = "https://pypi.tuna.tsinghua.edu.cn/simple/"
YANDEX_SIMPLE_URL = "https://pypi.yandex.ru/simple/"

DEFAULT_INDEXES = (
    PYPI_SIMPLE_URL,
    TSINGHUA_SIMPLE_URL,
    YANDEX_SIMPLE_URL,
)

HASH_ALGORITHMS = frozenset(
    {
        "sha256",
        "sha512",
        "sha384",
        "sha224",
        "sha1",
        "md5",
    }
)

SOURCE_SUFFIXES = (
    ".tar.gz",
    ".tar.bz2",
    ".tar.bz",
    ".tar.xz",
    ".tar.lz",
    ".tar.lzma",
    ".tar.zst",
    ".tgz",
    ".tbz",
    ".tbz2",
    ".txz",
    ".tlz",
    ".zip",
    ".tar",
)

# Higher number means stronger/preferred digest when multiple hashes are present.
HASH_PREFERENCE = {
    "sha512": 6,
    "sha384": 5,
    "sha256": 4,
    "sha224": 3,
    "sha1": 2,
    "md5": 1,
}

CHUNK_SIZE = 1024 * 1024
PARALLEL_DOWNLOAD_THRESHOLD = 5 * 1024 * 1024  # 5 MiB
DEFAULT_PARALLEL_WORKERS = min(8, max(2, os.cpu_count() or 2))

SIMPLE_ACCEPT_HEADER = ", ".join(
    (
        "application/vnd.pypi.simple.v1+json",
        "application/vnd.pypi.simple.v1+html; q=0.1",
        "text/html; q=0.01",
    )
)

JSON_SIMPLE_CONTENT_TYPES = frozenset(
    {
        "application/vnd.pypi.simple.v1+json",
    }
)

HTML_SIMPLE_CONTENT_TYPES = frozenset(
    {
        "application/vnd.pypi.simple.v1+html",
        "text/html",
    }
)


@dataclass(frozen=True, slots=True)
class Link:
    """A downloadable package artifact discovered in a simple-index response."""

    url: str
    comes_from: str | None = None
    requires_python: str | None = None
    yanked: str | None = None
    hashes: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Merge hash fragments such as '#sha256=<digest>' into hashes."""
        fragment = urlparse(self.url).fragment
        if not fragment:
            return

        hashes = dict(self.hashes)

        for algorithm, values in parse_qs(fragment).items():
            if algorithm in HASH_ALGORITHMS and values:
                hashes.setdefault(algorithm, values[0])

        if hashes != self.hashes:
            object.__setattr__(self, "hashes", hashes)

    @property
    def url_without_fragment(self) -> str:
        """Artifact URL excluding '#hash=...' fragments."""
        return self.url.split("#", 1)[0]

    @property
    def parsed_url(self):
        return urlparse(self.url_without_fragment)

    @property
    def filename(self) -> str:
        """Unquoted filename extracted from the URL path."""
        return unquote(self.parsed_url.path.rsplit("/", 1)[-1])

    @property
    def is_wheel(self) -> bool:
        return self.filename.endswith(".whl")

    @property
    def is_source_archive(self) -> bool:
        return self.filename.lower().endswith(SOURCE_SUFFIXES)

    @property
    def is_file(self) -> bool:
        return self.parsed_url.scheme == "file"

    @property
    def file_path(self) -> Path:
        """Return a local file path for file:// URLs."""
        if not self.is_file:
            raise ValueError(f"not a file URL: {self.url}")

        return Path(unquote(self.parsed_url.path))

    def __repr__(self) -> str:
        return f"<Link {self.url}>"


@dataclass(frozen=True, slots=True)
class Package:
    """A resolved package name/version/link candidate."""

    name: str
    version: str
    link: Link

    @property
    def parsed_version(self) -> Version:
        return Version(self.version)

    def as_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "link": self.link.url,
            "filename": self.link.filename,
            "requires_python": self.link.requires_python,
            "yanked": self.link.yanked,
            "hashes": self.link.hashes,
        }


@dataclass(slots=True)
class TargetPython:
    """Target interpreter/platform configuration used for wheel compatibility."""

    py_version: tuple[int, ...] | None = None
    abis: list[str] | None = None
    implementation: str | None = None
    platforms: list[str] | None = None
    _tags: list[Tag] | None = field(default=None, init=False, repr=False)

    def supported_tags(self) -> list[Tag]:
        """Return tags accepted by this target environment."""
        if self._tags is None:
            self._tags = self._compute_tags()
        return self._tags

    def python_version_str(self) -> str:
        """Return target version in Python Requires-Python format."""
        version = self.py_version or sys.version_info[:2]
        return ".".join(str(value) for value in version[:2])

    def _compute_tags(self) -> list[Tag]:
        implementation = self.implementation or interpreter_name()
        python_version = self.py_version[:2] if self.py_version else None

        version_digits = (
            "".join(map(str, python_version))
            if python_version
            else interpreter_version()
        )

        interpreter = f"{implementation}{version_digits}"
        tags: list[Tag] = []

        if implementation == "cp":
            tags.extend(cpython_tags(python_version, self.abis, self.platforms))
        else:
            tags.extend(generic_tags(interpreter, self.abis, self.platforms))

        tags.extend(compatible_tags(python_version, interpreter, self.platforms))
        return tags


class SimpleHTMLParser(HTMLParser):
    """Extract artifact anchors and optional base URL from a HTML simple index."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url: str | None = None
        self.anchors: list[dict[str, str | None]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag == "base" and self.base_url is None:
            self.base_url = dict(attrs).get("href")
        elif tag == "a":
            self.anchors.append(dict(attrs))


def parse_html_simple_page(response: httpx.Response) -> Iterator[Link]:
    """Yield package links from a PEP 503 HTML response."""
    parser = SimpleHTMLParser()
    parser.feed(response.text)

    base_url = parser.base_url or str(response.url)

    for attrs in parser.anchors:
        href = attrs.get("href")
        if not href:
            continue

        yanked = attrs.get("data-yanked")

        yield Link(
            url=urljoin(base_url, href),
            comes_from=base_url,
            requires_python=attrs.get("data-requires-python"),
            yanked="" if yanked == "" else yanked,
        )


def parse_json_simple_page(response: httpx.Response) -> Iterator[Link]:
    """Yield package links from a PEP 691 JSON response."""
    data = response.json()
    base_url = str(response.url)

    for file_data in data.get("files", ()):
        artifact_url = file_data.get("url")
        if not artifact_url:
            continue

        yanked = file_data.get("yanked")

        yield Link(
            url=urljoin(base_url, artifact_url),
            comes_from=base_url,
            requires_python=file_data.get("requires-python"),
            yanked=(
                yanked if isinstance(yanked, str) else "yanked" if yanked else None
            ),
            hashes=file_data.get("hashes") or {},
        )


def fetch_simple_page(client: httpx.Client, url: str) -> list[Link]:
    """Fetch one simple-index page and parse JSON or HTML response data."""
    response = client.get(url, headers={"Accept": SIMPLE_ACCEPT_HEADER})
    response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    content_type = content_type.split(";", 1)[0].strip().lower()

    if content_type in JSON_SIMPLE_CONTENT_TYPES:
        return list(parse_json_simple_page(response))

    if content_type in HTML_SIMPLE_CONTENT_TYPES:
        return list(parse_html_simple_page(response))

    raise ValueError(
        f"unsupported simple-index content type {content_type!r} from {url}"
    )


def source_filename_without_extension(filename: str) -> str:
    """Remove the recognized source-distribution extension from a filename."""
    lower_filename = filename.lower()

    for suffix in sorted(SOURCE_SUFFIXES, key=len, reverse=True):
        if lower_filename.endswith(suffix):
            return filename[: -len(suffix)]

    return filename


def requires_python_matches(
    requires_python: str,
    target_python: TargetPython,
) -> bool:
    """Return whether a Requires-Python specifier supports the target Python."""
    try:
        specifier = SpecifierSet(requires_python)
    except InvalidSpecifier:
        logger.warning(
            "Ignoring invalid Requires-Python specifier: {}", requires_python
        )
        return True

    return specifier.contains(
        target_python.python_version_str(),
        prereleases=True,
    )


def wheel_tag_priority(link: Link, priorities: dict[Tag, int]) -> int:
    """
    Return best wheel-tag priority.

    Lower values are better. A value after the priorities range means
    unsupported/non-wheel.
    """
    unsupported = len(priorities) + 1

    if not link.is_wheel:
        return unsupported

    try:
        _, _, _, wheel_tags = parse_wheel_filename(link.filename)
    except (InvalidWheelFilename, InvalidVersion):
        return unsupported

    return min(
        (priorities.get(tag, unsupported) for tag in wheel_tags),
        default=unsupported,
    )


def candidate_from_link(
    link: Link,
    requirement: Requirement,
    target_python: TargetPython,
    tag_priorities: dict[Tag, int],
    *,
    allow_prereleases: bool | None,
    no_binary: bool,
    only_binary: bool,
) -> Package | None:
    """Build a matching package candidate, or return None."""
    if link.is_wheel:
        if no_binary:
            return None

        try:
            project_name, version, _, wheel_tags = parse_wheel_filename(link.filename)
        except (InvalidWheelFilename, InvalidVersion):
            return None

        if canonicalize_name(project_name) != canonicalize_name(requirement.name):
            return None

        if not requirement.specifier.contains(version, prereleases=allow_prereleases):
            return None

        if not any(tag in tag_priorities for tag in wheel_tags):
            return None

    else:
        if only_binary or not link.is_source_archive:
            return None

        source_name = source_filename_without_extension(link.filename)
        project_name, separator, version_string = source_name.rpartition("-")

        if not separator or not project_name or not version_string:
            return None

        if canonicalize_name(project_name) != canonicalize_name(requirement.name):
            return None

        try:
            version = Version(version_string)
        except InvalidVersion:
            return None

        if not requirement.specifier.contains(version, prereleases=allow_prereleases):
            return None

    if link.requires_python and not requires_python_matches(
        link.requires_python,
        target_python,
    ):
        return None

    return Package(
        name=requirement.name,
        version=str(version),
        link=link,
    )


class PackageFinder:
    """Collect, filter, rank, and resolve package distribution candidates."""

    def __init__(
        self,
        index_urls: Iterable[str] = (),
        find_links: Iterable[str] = (),
        target_python: TargetPython | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.sources: list[tuple[str, str]] = []

        indexes = list(index_urls)
        if not indexes:
            indexes = list(DEFAULT_INDEXES)

        self.sources.extend(("index", url) for url in indexes)
        self.sources.extend(("find_links", url) for url in find_links)

        self.target_python = target_python or TargetPython()
        self._client = client

        self._tag_priorities = {
            tag: priority
            for priority, tag in enumerate(self.target_python.supported_tags())
        }

    @property
    def client(self) -> httpx.Client:
        """Create the shared index client lazily."""
        if self._client is None:
            self._client = httpx.Client(
                follow_redirects=True,
                timeout=httpx.Timeout(30.0, connect=10.0),
            )

        return self._client

    def close(self) -> None:
        """Close the owned HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "PackageFinder":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def find_matches(
        self,
        requirement: Requirement,
        *,
        allow_prereleases: bool | None = None,
        no_binary: bool = False,
        only_binary: bool = False,
    ) -> list[Package]:
        """Return matching distributions, sorted with the best candidate first."""
        candidates: list[Package] = []
        seen_urls: set[str] = set()

        for source_type, source_url in self.sources:
            try:
                links = self._collect_links(source_type, source_url, requirement)
            except (httpx.HTTPError, OSError, ValueError) as exc:
                logger.warning(
                    "Could not query {} source {}: {}",
                    source_type,
                    source_url,
                    exc,
                )
                continue

            for link in links:
                package = candidate_from_link(
                    link,
                    requirement,
                    self.target_python,
                    self._tag_priorities,
                    allow_prereleases=allow_prereleases,
                    no_binary=no_binary,
                    only_binary=only_binary,
                )

                if package is None:
                    continue

                normalized_url = package.link.url_without_fragment
                if normalized_url in seen_urls:
                    continue

                seen_urls.add(normalized_url)
                candidates.append(package)

        candidates.sort(key=self._sort_key, reverse=True)
        return candidates

    def _collect_links(
        self,
        source_type: str,
        source_url: str,
        requirement: Requirement,
    ) -> list[Link]:
        """Fetch links from an index URL or a direct find-links source."""
        if source_type == "index":
            package_url = urljoin(
                source_url.rstrip("/") + "/",
                canonicalize_name(requirement.name) + "/",
            )
        else:
            package_url = source_url

            if not package_url.startswith(("http://", "https://", "file://")):
                package_url = Path(package_url).expanduser().resolve().as_uri()

        if package_url.startswith("file://"):
            return self._collect_file_links(package_url)

        return fetch_simple_page(self.client, package_url)

    @staticmethod
    def _collect_file_links(url: str) -> list[Link]:
        """
        Resolve a file:// find-links directory or a direct file artifact.

        Local HTML pages are intentionally not parsed; use an HTTP simple index
        when HTML index parsing is needed.
        """
        path = Path(unquote(urlparse(url).path))

        if path.is_file():
            return [Link(url=path.resolve().as_uri())]

        if not path.is_dir():
            raise FileNotFoundError(path)

        return [
            Link(url=item.resolve().as_uri())
            for item in path.iterdir()
            if item.is_file()
        ]

    def _sort_key(self, package: Package) -> tuple[int, Version, int, int, str]:
        """
        Candidate ranking:

        1. Non-yanked artifacts.
        2. Newer package version.
        3. Source distributions before wheels.
        4. Better source archive / wheel tag.
        5. Stable deterministic filename order.
        """
        link = package.link
        is_yanked = link.yanked is not None

        artifact_preference = source_artifact_priority(link)
        tag_priority = wheel_tag_priority(link, self._tag_priorities)

        return (
            -int(is_yanked),
            package.parsed_version,
            artifact_preference,
            -tag_priority,
            link.filename.lower(),
        )


def source_artifact_priority(link: Link) -> int:
    """Rank source archive formats; source archives always outrank wheels."""
    filename = link.filename.lower()

    if filename.endswith(".tar.gz") or filename.endswith(".tgz"):
        return 30

    if filename.endswith(".tar.bz2") or filename.endswith(".tar.bz"):
        return 29

    if filename.endswith(".zip"):
        return 28

    if link.is_source_archive:
        return 27

    return 0


def choose_hash(hashes: dict[str, str]) -> tuple[str, str] | None:
    """Choose the strongest supported hash supplied by the package index."""
    valid_hashes = [
        (algorithm.lower(), digest.lower())
        for algorithm, digest in hashes.items()
        if algorithm.lower() in HASH_ALGORITHMS
    ]

    if not valid_hashes:
        return None

    return max(
        valid_hashes,
        key=lambda item: HASH_PREFERENCE.get(item[0], 0),
    )


def calculate_file_hash(path: Path, algorithm: str) -> str:
    """Return a hexadecimal digest for a file."""
    digest = hashlib.new(algorithm)

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(CHUNK_SIZE), b""):
            digest.update(chunk)

    return digest.hexdigest()


def verify_hashes(path: Path, hashes: dict[str, str]) -> bool:
    """
    Verify repository-provided hashes.

    If no hash exists in the simple index, the download cannot be
    cryptographically authenticated, but archive integrity is still checked.
    """
    selected_hash = choose_hash(hashes)

    if selected_hash is None:
        logger.warning(
            "No published hash for {}; only archive readability will be checked",
            path.name,
        )
        return True

    algorithm, expected = selected_hash
    actual = calculate_file_hash(path, algorithm)

    if actual.lower() != expected.lower():
        logger.error(
            "Hash mismatch for {} using {}: expected {}, got {}",
            path,
            algorithm,
            expected,
            actual,
        )
        return False

    logger.debug("Verified {} checksum for {}", algorithm, path.name)
    return True


def verify_archive_integrity(path: Path) -> bool:
    """
    Check whether a downloaded source archive or wheel can be opened.

    This complements cryptographic hash validation. It does not prove package
    safety; only index hashes provide cryptographic artifact verification.
    """
    filename = path.name.lower()

    try:
        if filename.endswith(".whl") or filename.endswith(".zip"):
            with zipfile.ZipFile(path) as archive:
                corrupt_member = archive.testzip()

            if corrupt_member is not None:
                logger.error(
                    "Corrupt ZIP member {} in {}",
                    corrupt_member,
                    path,
                )
                return False

            return True

        if any(filename.endswith(suffix) for suffix in SOURCE_SUFFIXES):
            try:
                with tarfile.open(path, mode="r:*") as archive:
                    for _ in archive:
                        pass
                return True
            except tarfile.ReadError:
                # Some uncommon formats may not be supported by Python's tarfile.
                # A hash validation, if supplied, still verifies exact bytes.
                logger.debug(
                    "Could not inspect {} as a tar archive; skipping tar read check",
                    path.name,
                )
                return True

    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        logger.error("Archive integrity check failed for {}: {}", path, exc)
        return False

    return True


def remote_file_size(client: httpx.Client, url: str) -> int | None:
    """Return remote content length when the server provides it."""
    try:
        response = client.head(url, follow_redirects=True)
        response.raise_for_status()

        value = response.headers.get("content-length")
        return int(value) if value and value.isdigit() else None
    except (httpx.HTTPError, ValueError):
        return None


def server_supports_ranges(client: httpx.Client, url: str) -> bool:
    """Return whether the remote server appears to support byte ranges."""
    try:
        response = client.head(url, follow_redirects=True)
        response.raise_for_status()

        return response.headers.get("accept-ranges", "").lower() == "bytes"
    except httpx.HTTPError:
        return False


def download_httpx_single(
    client: httpx.Client,
    url: str,
    destination: Path,
) -> None:
    """Download one URL using streamed httpx I/O."""
    with client.stream("GET", url) as response:
        response.raise_for_status()

        with destination.open("wb") as file:
            for chunk in response.iter_bytes(CHUNK_SIZE):
                file.write(chunk)


def download_httpx_parallel(
    url: str,
    destination: Path,
    size: int,
    workers: int = DEFAULT_PARALLEL_WORKERS,
) -> None:
    """
    Download a large HTTP file through parallel byte ranges.

    The partial files are merged only after every range succeeds.
    """
    workers = min(workers, max(2, (size + CHUNK_SIZE - 1) // CHUNK_SIZE))
    part_dir = destination.with_name(destination.name + ".parts")

    if part_dir.exists():
        shutil.rmtree(part_dir)

    part_dir.mkdir(parents=True, exist_ok=True)

    chunk_span = (size + workers - 1) // workers
    ranges: list[tuple[int, int, Path]] = []

    for index in range(workers):
        start = index * chunk_span
        end = min(size - 1, start + chunk_span - 1)

        if start > end:
            continue

        ranges.append((start, end, part_dir / f"{index:03d}.part"))

    def download_range(start: int, end: int, part_path: Path) -> None:
        headers = {"Range": f"bytes={start}-{end}"}

        with httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(90.0, connect=15.0),
        ) as client:
            with client.stream("GET", url, headers=headers) as response:
                if response.status_code != 206:
                    raise httpx.HTTPStatusError(
                        f"Server ignored byte range {start}-{end}",
                        request=response.request,
                        response=response,
                    )

                with part_path.open("wb") as file:
                    for chunk in response.iter_bytes(CHUNK_SIZE):
                        file.write(chunk)

        expected_size = end - start + 1
        actual_size = part_path.stat().st_size

        if actual_size != expected_size:
            raise OSError(
                f"incomplete range {start}-{end}: "
                f"expected {expected_size}, received {actual_size}"
            )

    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=len(ranges)) as executor:
            futures = [
                executor.submit(download_range, start, end, part_path)
                for start, end, part_path in ranges
            ]

            for future in as_completed(futures):
                future.result()

        with destination.open("wb") as output:
            for _, _, part_path in ranges:
                with part_path.open("rb") as part:
                    shutil.copyfileobj(part, output, length=CHUNK_SIZE)

        if destination.stat().st_size != size:
            raise OSError(
                f"download size mismatch: expected {size}, "
                f"got {destination.stat().st_size}"
            )

    finally:
        shutil.rmtree(part_dir, ignore_errors=True)


def download_requests(url: str, destination: Path) -> None:
    """Download using requests, imported only when selected."""
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError(
            "The requests backend requires: pip install requests"
        ) from exc

    with requests.get(url, stream=True, timeout=(15, 90)) as response:
        response.raise_for_status()

        with destination.open("wb") as file:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    file.write(chunk)


def download_pycurl(url: str, destination: Path) -> None:
    """Download using pycurl, imported only when selected."""
    try:
        import pycurl
    except ImportError as exc:
        raise RuntimeError("The pycurl backend requires: pip install pycurl") from exc

    curl = pycurl.Curl()

    try:
        with destination.open("wb") as file:
            curl.setopt(curl.URL, url)
            curl.setopt(curl.FOLLOWLOCATION, True)
            curl.setopt(curl.CONNECTTIMEOUT, 15)
            curl.setopt(curl.TIMEOUT, 120)
            curl.setopt(curl.WRITEDATA, file)
            curl.perform()

            status = curl.getinfo(curl.RESPONSE_CODE)
            if status >= 400:
                raise OSError(f"HTTP status {status} while downloading {url}")
    finally:
        curl.close()


def download_aria2c(url: str, destination: Path) -> None:
    """Download using aria2c subprocess with split/parallel connections."""
    aria2c = shutil.which("aria2c")

    if aria2c is None:
        raise RuntimeError(
            "aria2c backend selected, but aria2c is not installed or not in PATH"
        )

    command = [
        aria2c,
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        "--continue=true",
        "--file-allocation=none",
        "--max-connection-per-server=8",
        "--min-split-size=5M",
        "--split=8",
        "--summary-interval=0",
        "--dir",
        str(destination.parent),
        "--out",
        destination.name,
        url,
    ]

    subprocess.run(command, check=True)


def download(
    link: Link,
    destination_dir: Path,
    *,
    backend: str = "httpx",
    client: httpx.Client | None = None,
) -> Path:
    """
    Download an artifact and validate its cryptographic hash/archive integrity.

    Existing valid files are reused. Invalid or incomplete cached files are
    removed before downloading again.
    """
    destination_dir.mkdir(parents=True, exist_ok=True)

    if link.is_file:
        source_path = link.file_path

        if not source_path.is_file():
            raise FileNotFoundError(source_path)

        if not verify_hashes(source_path, link.hashes):
            raise ValueError(f"hash mismatch for local artifact: {source_path}")

        if not verify_archive_integrity(source_path):
            raise ValueError(f"invalid archive: {source_path}")

        return source_path

    filename = link.filename or "download.bin"
    destination = destination_dir / filename

    if destination.exists():
        if verify_hashes(destination, link.hashes) and verify_archive_integrity(
            destination
        ):
            logger.info("Using cached artifact: {}", destination)
            return destination

        logger.warning("Removing invalid cached artifact: {}", destination)
        destination.unlink(missing_ok=True)

    temporary_destination = destination.with_name(destination.name + ".part")
    temporary_destination.unlink(missing_ok=True)

    logger.info("Downloading {} via {}", link.url_without_fragment, backend)

    try:
        if backend == "httpx":
            owns_client = client is None
            active_client = client or httpx.Client(
                follow_redirects=True,
                timeout=httpx.Timeout(90.0, connect=15.0),
            )

            try:
                file_size = remote_file_size(active_client, link.url_without_fragment)
                range_supported = server_supports_ranges(
                    active_client,
                    link.url_without_fragment,
                )

                if (
                    file_size is not None
                    and file_size > PARALLEL_DOWNLOAD_THRESHOLD
                    and range_supported
                ):
                    logger.info(
                        "Using parallel ranged download ({} MiB)",
                        round(file_size / 1024 / 1024, 2),
                    )
                    download_httpx_parallel(
                        link.url_without_fragment,
                        temporary_destination,
                        file_size,
                    )
                else:
                    download_httpx_single(
                        active_client,
                        link.url_without_fragment,
                        temporary_destination,
                    )
            finally:
                if owns_client:
                    active_client.close()

        elif backend == "requests":
            download_requests(link.url_without_fragment, temporary_destination)

        elif backend == "pycurl":
            download_pycurl(link.url_without_fragment, temporary_destination)

        elif backend == "aria2c":
            download_aria2c(link.url_without_fragment, temporary_destination)

        else:
            raise ValueError(f"unsupported backend: {backend}")

        temporary_destination.replace(destination)

        if not verify_hashes(destination, link.hashes):
            destination.unlink(missing_ok=True)
            raise ValueError(f"hash mismatch for {link.url_without_fragment}")

        if not verify_archive_integrity(destination):
            destination.unlink(missing_ok=True)
            raise ValueError(f"archive integrity verification failed: {destination}")

        logger.success("Downloaded {}", destination)
        return destination

    except Exception:
        temporary_destination.unlink(missing_ok=True)
        raise


def parse_python_version(value: str) -> tuple[int, ...]:
    """Parse --py-version such as 3.12 or 3.12.1."""
    parts = value.split(".")

    if not parts or any(not part.isdigit() for part in parts):
        raise argparse.ArgumentTypeError(
            f"invalid Python version: {value!r}; expected X.Y"
        )

    return tuple(int(part) for part in parts)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="pkgfetch",
        description=(
            "Find and download Python distributions from PEP 503/691 indexes."
        ),
    )

    parser.add_argument(
        "requirement",
        type=Requirement,
        help="PEP 508 requirement, for example: requests>=2.28",
    )

    parser.add_argument(
        "-i",
        "--index-url",
        action="append",
        default=[],
        metavar="URL",
        help=(
            "Simple index URL, repeatable. "
            "If omitted: PyPI, Tsinghua, and Yandex are tried in order."
        ),
    )

    parser.add_argument(
        "-f",
        "--find-link",
        action="append",
        default=[],
        metavar="DIR_OR_URL",
        help="Additional find-links source, repeatable.",
    )

    parser.add_argument(
        "-d",
        "--dest",
        type=Path,
        default=Path("."),
        metavar="DIR",
        help="Download destination directory, default: current directory.",
    )

    parser.add_argument(
        "-b",
        "--backend",
        choices=("httpx", "requests", "pycurl", "aria2c"),
        default="httpx",
        help=(
            "Download backend. httpx supports internal parallel range downloads; "
            "aria2c uses external parallel downloading."
        ),
    )

    parser.add_argument(
        "--py-version",
        type=parse_python_version,
        default=None,
        metavar="X.Y",
        help="Override target Python version.",
    )

    parser.add_argument(
        "--platform",
        action="append",
        default=[],
        metavar="TAG",
        help="Override target platform tag, repeatable.",
    )

    parser.add_argument(
        "--abi",
        action="append",
        default=[],
        metavar="TAG",
        help="Override ABI tag, repeatable.",
    )

    parser.add_argument(
        "--impl",
        default=None,
        metavar="IMPL",
        help="Override Python implementation, for example cp or pp.",
    )

    binary_group = parser.add_mutually_exclusive_group()

    binary_group.add_argument(
        "--no-binary",
        action="store_true",
        help="Exclude wheels and select source archives only.",
    )

    binary_group.add_argument(
        "--only-binary",
        action="store_true",
        help="Select wheels only.",
    )

    parser.add_argument(
        "--pre",
        action="store_true",
        help="Allow pre-release versions.",
    )

    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Download every matching candidate, rather than only the best.",
    )

    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Print JSON metadata.",
    )

    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Resolve candidates and print metadata without downloading.",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )

    return parser


def configure_logging(verbose: bool) -> None:
    """Configure concise loguru output."""
    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG" if verbose else "INFO",
        format="<level>{level: <8}</level> {message}",
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    target_python = TargetPython(
        py_version=args.py_version,
        abis=args.abi or None,
        implementation=args.impl,
        platforms=args.platform or None,
    )

    with PackageFinder(
        index_urls=args.index_url,
        find_links=args.find_link,
        target_python=target_python,
    ) as finder:
        matches = finder.find_matches(
            args.requirement,
            allow_prereleases=True if args.pre else None,
            no_binary=args.no_binary,
            only_binary=args.only_binary,
        )

        if not matches:
            logger.error(
                "No matching distributions found for {}",
                args.requirement,
            )
            return 1

        if not args.all:
            matches = matches[:1]

        results: list[dict[str, Any]] = []

        for package in matches:
            metadata = package.as_json()

            if not args.no_download:
                try:
                    local_path = download(
                        package.link,
                        args.dest.expanduser().resolve(),
                        backend=args.backend,
                        client=finder.client if args.backend == "httpx" else None,
                    )
                except (
                    httpx.HTTPError,
                    OSError,
                    RuntimeError,
                    subprocess.CalledProcessError,
                    ValueError,
                ) as exc:
                    logger.exception(
                        "Download failed for {}: {}",
                        package.link.url_without_fragment,
                        exc,
                    )
                    return 2

                metadata["local_path"] = str(local_path)

            results.append(metadata)

    if args.json or args.no_download:
        output: dict[str, Any] | list[dict[str, Any]]
        output = results[0] if len(results) == 1 else results
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        for result in results:
            print(result["local_path"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
