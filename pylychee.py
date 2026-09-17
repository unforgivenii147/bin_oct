#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python utility that scans a folder for .md/.html/.htm files, inlines local
image references as base64 data URIs inside HTML attributes (href/src) and Markdown
image links, drops image references (remote and local) that are unreachable, and
reports every removal. Use multiprocessing.Pool.apply_async with a fixed pool of 8
workers, pathlib for all path handling, loguru for logging, complete type hints
(mypy/pyright strict compatible), and docstrings on every function. No CLI flags
control parallelism; only positional root plus --timeout are accepted.
"""

from __future__ import annotations

import argparse
import base64
import mimetypes
import re
import urllib.error
import urllib.request
from collections.abc import Iterable
from multiprocessing import Pool
from pathlib import Path
from typing import Final
from urllib.parse import unquote, urldefrag

from loguru import logger

EXT_IMAGE: Final[frozenset[str]] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg"}
)
HTTP_SCHEMES: Final[tuple[str, ...]] = ("http://", "https://")
HTML_ATTR_RE: Final[re.Pattern[str]] = re.compile(
    r'(?P<attr>href|src)\s*=\s*(?P<q>["\'])(?P<url>.*?)(?P=q)', re.IGNORECASE
)
MD_IMAGE_RE: Final[re.Pattern[str]] = re.compile(
    r"!\[([^\]]*?)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)
MD_LINK_RE: Final[re.Pattern[str]] = re.compile(
    r"\[(?P<text>[^\]]*?)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)
DEFAULT_TIMEOUT: Final[int] = 8
POOL_WORKERS: Final[int] = 8
TARGET_EXTS: Final[tuple[str, ...]] = (".md", ".html", ".htm")


def _strip_fragment_query(u: str) -> str:
    """Remove URL fragment and query string from a URL or path."""
    v, _ = urldefrag(u)
    if "?" in v:
        v = v.split("?", 1)[0]
    return v


def _guess_ext(u: str) -> str:
    """Return the lowercased file extension of a URL or path, ignoring query/fragment."""
    p = _strip_fragment_query(u)
    return Path(p).suffix.lower()


def _is_remote(u: str) -> bool:
    """Return True if the reference is an absolute HTTP(S) URL."""
    s = u.strip()
    return any(s.startswith(x) for x in HTTP_SCHEMES)


def _is_local_ref(u: str) -> bool:
    """Return True if the reference is a non-empty local path (not a fragment)."""
    s = u.strip()
    if not s:
        return False
    if s.startswith("#"):
        return False
    return not _is_remote(s)


def _is_imageish(u: str) -> bool:
    """Return True if the reference looks like an image by extension."""
    return _guess_ext(u) in EXT_IMAGE


def _read_bytes(path: Path) -> bytes:
    """Read and return the raw bytes of a file."""
    return path.read_bytes()


def _local_target_resolve(base_dir: Path, u: str) -> Path | None:
    """Resolve a local reference relative to base_dir, returning None on absolute paths."""
    s = u.strip()
    if not s:
        return None
    if s.startswith("/"):
        return None
    if "#" in s or "?" in s:
        s = _strip_fragment_query(s)
    s = unquote(s)
    try:
        return (base_dir / s).resolve()
    except OSError:
        return None


def _mime_for_local(path: Path) -> str:
    """Guess the MIME type for a local file, defaulting to application/octet-stream."""
    if path.suffix.lower() == ".svg":
        return "image/svg+xml"
    m, _ = mimetypes.guess_type(str(path))
    return m or "application/octet-stream"


def _to_data_uri(path: Path) -> str:
    """Encode a local file as a base64 data URI."""
    mime = _mime_for_local(path)
    raw = _read_bytes(path)
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _http_check(url: str, timeout: int) -> bool:
    """Return True if the remote URL responds successfully (HEAD, falling back to GET)."""
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", 200)
            return code < 400
    except Exception:
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                code = getattr(resp, "status", 200)
                return code < 400
        except Exception:
            return False


def _replace_html(html: str, file_dir: Path, timeout: int) -> tuple[str, list[str]]:
    """Inline local images and prune unreachable images in HTML href/src attributes."""
    removals: list[str] = []

    def html_attr_repl(m: re.Match[str]) -> str:
        attr = m.group("attr")
        q = m.group("q")
        url = m.group("url")
        raw = url
        target = url.strip()
        if not target or target.startswith(("#", "data:")):
            return m.group(0)
        if _is_remote(target):
            if _is_imageish(target) and not _http_check(target, timeout):
                removals.append(f"REMOTE_UNAVAILABLE_IMAGE {attr}={raw}")
                return f"{attr}={q}{q}"
            return m.group(0)
        if _is_local_ref(target):
            local_path = _local_target_resolve(file_dir, target)
            if local_path is None or not local_path.is_file():
                removals.append(f"LOCAL_UNAVAILABLE {attr}={raw}")
                return m.group(0)
            if _is_imageish(target):
                try:
                    data_uri = _to_data_uri(local_path)
                except Exception:
                    removals.append(f"LOCAL_INLINE_FAILED {attr}={raw}")
                    return m.group(0)
                return f"{attr}={q}{data_uri}{q}"
        return m.group(0)

    out = HTML_ATTR_RE.sub(html_attr_repl, html)
    return out, removals


def _replace_md(md: str, file_dir: Path, timeout: int) -> tuple[str, list[str]]:
    """Inline local images and prune unreachable images in Markdown images/links."""
    removals: list[str] = []

    def replace_md_images(match: re.Match[str]) -> str:
        url = match.group("url").strip()
        if not url or url.startswith(("#", "data:")):
            return match.group(0)
        if _is_remote(url):
            if _is_imageish(url) and not _http_check(url, timeout):
                removals.append(f"REMOTE_UNAVAILABLE_IMAGE_MD {url}")
                return ""
            return match.group(0)
        if _is_local_ref(url) and _is_imageish(url):
            local_path = _local_target_resolve(file_dir, url)
            if local_path is None or not local_path.is_file():
                removals.append(f"LOCAL_UNAVAILABLE_MD {url}")
                return match.group(0)
            try:
                data_uri = _to_data_uri(local_path)
            except Exception:
                removals.append(f"LOCAL_INLINE_FAILED_MD {url}")
                return match.group(0)
            text = match.group(1) or ""
            return f"![{text}]({data_uri})"
        return match.group(0)

    def replace_md_links(match: re.Match[str]) -> str:
        url = match.group("url").strip()
        if not url or url.startswith(("#", "data:")):
            return match.group(0)
        if _is_remote(url):
            if _is_imageish(url) and not _http_check(url, timeout):
                removals.append(f"REMOTE_UNAVAILABLE_IMAGE_MD_LINK {url}")
                return match.group(0).replace(f"({url})", "()")
            return match.group(0)
        if _is_local_ref(url):
            local_path = _local_target_resolve(file_dir, url)
            if local_path is None or not local_path.is_file():
                removals.append(f"LOCAL_UNAVAILABLE_MD_LINK {url}")
            return match.group(0)
        return match.group(0)

    out = MD_IMAGE_RE.sub(replace_md_images, md)
    out = MD_LINK_RE.sub(replace_md_links, out)
    return out, removals


def process_file(args: tuple[str, int]) -> list[str]:
    """Process a single file: inline/prune references and return report lines."""
    path_str, timeout = args
    path = Path(path_str)
    file_dir = path.parent
    content = path.read_text(encoding="utf-8", errors="replace")
    report: list[str] = []
    new_content: str = content
    suffix = path.suffix.lower()
    if suffix in (".html", ".htm"):
        new_content, report = _replace_html(content, file_dir, timeout)
    elif suffix == ".md":
        new_content, report = _replace_md(content, file_dir, timeout)
    else:
        return []
    if new_content != content:
        path.write_text(new_content, encoding="utf-8", errors="replace")
    return report


def iter_files(root: Path, exts: tuple[str, ...]) -> list[str]:
    """Return all files under root (recursively) whose suffix matches exts."""
    out: list[str] = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            out.append(str(p))
    return out


def main() -> int:
    """CLI entry point: scan a folder and process all markdown/HTML files."""
    parser = argparse.ArgumentParser()
    parser.add_argument("root", help="Folder to scan")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        logger.error("root is not a directory: {}", root)
        return 2

    files = iter_files(root, TARGET_EXTS)
    if not files:
        return 0

    timeout: int = args.timeout
    tasks: list[tuple[str, int]] = [(fp, timeout) for fp in files]
    all_reports: list[str] = []

    with Pool(processes=POOL_WORKERS) as pool:
        results: Iterable[object] = [
            pool.apply_async(process_file, (task,)) for task in tasks
        ]
        for fp, res in zip(files, results):
            try:
                r = res.get()  # type: ignore[attr-defined]
            except Exception as e:
                all_reports.append(f"FAILED {fp} {e}")
                continue
            if isinstance(r, list):
                all_reports.extend(r)

    for line in all_reports:
        print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
