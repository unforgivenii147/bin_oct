#!/data/data/com.termux/files/home/.local/bin/python
"""
urlkit.py — unified URL extraction / cleaning / processing toolkit.

Merges the behavior of:
    clean_urls.py, exlinks.py, file_urls.py, filter_jscss_links.py,
    furl.py, move_gitlinks.py, process_urls.py, process_urls_aggresive.py,
    saveurl.py, split_urls.py, urlzz.py, xfile_urls.py

Third-party packages (imported lazily / optionally per subcommand):
    requests   — required by  fetch-files --download
    py7zr      — required to scan .7z archives
    pywebcopy  — required by  save-page
    chardet    — optional; used for encoding auto-detection
    loguru     — optional; falls back to stdlib logging
    tqdm       — optional; falls back to no-op progress

Original → merged mapping
-------------------------
    clean_urls.py              -> python urlkit.py clean --input urls.txt
    exlinks.py                 -> python urlkit.py scan --archives-only .
    file_urls.py               -> python urlkit.py split --mode grouped -i urls.txt
    filter_jscss_links.py      -> python urlkit.py filter-jscss -i urls.txt
    furl.py                    -> python urlkit.py scan --exclude-git-from-output .
    move_gitlinks.py           -> python urlkit.py move-gitlinks urls.txt
    process_urls.py            -> python urlkit.py prune -i urls.txt
    process_urls_aggresive.py  -> python urlkit.py prune -i urls.txt --aggressive
    saveurl.py                 -> python urlkit.py save-page https://example.com
    split_urls.py              -> python urlkit.py split --mode by-ext -i urls.txt
    urlzz.py                   -> python urlkit.py scan --append /path/to/dir
    xfile_urls.py              -> python urlkit.py fetch-files -i urls.txt -d downloads

Run `python urlkit.py <subcommand> -h` for per-command help.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import tarfile
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from multiprocessing import Pool
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

# ---------------------------------------------------------------------------
# Optional third-party imports (kept soft so --help works without them)
# ---------------------------------------------------------------------------
try:
    from loguru import logger as _loguru_logger
except ImportError:
    _loguru_logger = None

try:
    from tqdm import tqdm as _tqdm
except ImportError:

    def _tqdm(it, **_kw):
        return it


try:
    import chardet  # type: ignore
except ImportError:
    chardet = None  # type: ignore


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
def log_info(msg: str) -> None:
    if _loguru_logger:
        _loguru_logger.info(msg)
    else:
        print(msg, file=sys.stderr)


def log_warning(msg: str) -> None:
    if _loguru_logger:
        _loguru_logger.warning(msg)
    else:
        print(f"WARNING: {msg}", file=sys.stderr)


def log_error(msg: str) -> None:
    if _loguru_logger:
        _loguru_logger.error(msg)
    else:
        print(f"ERROR: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Shared constants / defaults
# ---------------------------------------------------------------------------
URL_RE = re.compile(r'https?://[^\s<>"\'\)\]\}]+', re.IGNORECASE)
GITHUB_RE = re.compile(
    r'https?://(?:www\.)?github\.com/[^\s<>"\'\)\]\}]+',
    re.IGNORECASE,
)
GITHUB_REPO_RE = re.compile(
    r"https?://(?:www\.)?github\.com/[a-zA-Z0-9\-]+/[a-zA-Z0-9\-]+",
)

DEFAULT_SKIP_DIRS = ".git,__pycache__,.venv,venv,node_modules,.env,dist,build"
DEFAULT_GIT_HOSTS = (
    "github.com,gitlab.com,gitea.io,bitbucket.org,git.sr.ht,"
    "codeberg.org,gitbucket.org,gogs.io"
)

# Best-effort extension lists (originally from `dh.TXT_EXT` / `dh.BIN_EXT`).
# Override via --file-exts if you have the real values.
DEFAULT_FILE_EXTS = ",".join(
    sorted(
        {
            ".txt",
            ".md",
            ".rst",
            ".log",
            ".csv",
            ".tsv",
            ".json",
            ".xml",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".cfg",
            ".conf",
            ".html",
            ".htm",
            ".css",
            ".js",
            ".ts",
            ".py",
            ".rb",
            ".go",
            ".rs",
            ".java",
            ".c",
            ".h",
            ".cpp",
            ".hpp",
            ".sh",
            ".bash",
            ".zsh",
            ".pdf",
            ".zip",
            ".tar",
            ".gz",
            ".xz",
            ".7z",
            ".whl",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".webp",
            ".ico",
            ".bmp",
            ".ttf",
            ".woff",
            ".woff2",
            ".eot",
            ".otf",
            ".ttc",
        }
    )
)

ZIP_SUFFIXES = (".zip", ".whl")
TAR_SUFFIXES = (
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
)
SEVENZ_SUFFIXES = (".7z",)

# xfile_urls.py target extensions
FETCH_EXTS = (".css", ".ttf", ".woff", ".woff2", ".pdf")

# split_urls.py known extensions (by-ext mode)
BY_EXT_KNOWN = [
    "htm",
    "html",
    "js",
    "css",
    "pdf",
    "asp",
    "aspx",
    "php",
    "jsp",
    "jpg",
    "jpeg",
    "png",
    "gif",
    "svg",
    "webp",
    "zip",
    "rar",
    "7z",
    "tar",
    "gz",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "txt",
    "csv",
    "xml",
    "json",
    "mp3",
    "mp4",
    "avi",
    "mov",
    "wav",
    "exe",
    "dmg",
    "apk",
]


# ===========================================================================
# Shared helpers
# ===========================================================================
def _write_urls(path: Path, urls: Iterable[str], append: bool = False) -> None:
    """Write URLs (one per line) to *path*, optionally appending."""
    mode = "a" if append else "w"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode, encoding="utf-8") as f:
        if append and path.stat().st_size > 0:
            f.write("\n")
        f.writelines(f"{u}\n" for u in urls)


def _archive_kind(path: Path) -> Optional[str]:
    """Return 'zip', 'tar', '7z' or None based on filename."""
    name = path.name.lower()
    if name.endswith(ZIP_SUFFIXES):
        return "zip"
    if name.endswith(SEVENZ_SUFFIXES) and not name.endswith(".tar.7z"):
        return "7z"
    if any(name.endswith(s) for s in TAR_SUFFIXES):
        return "tar"
    return None


def _decode_bytes(data: bytes) -> str:
    """Decode bytes using utf-8 → chardet → latin-1 fallback."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if chardet is not None:
        det = chardet.detect(data) or {}
        enc = det.get("encoding")
        if isinstance(enc, str) and enc:
            try:
                return data.decode(enc, errors="ignore")
            except Exception:
                pass
    return data.decode("latin-1", errors="ignore")


def _read_text_file(path: Path) -> Optional[str]:
    """Read a text file trying common encodings (mirrors exlinks.py o())."""
    for enc in ("utf-8", "latin-1", "iso-8859-1", "cp1252"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            log_warning(f"Error reading {path} with {enc}: {exc}")
            continue
    try:
        raw = path.read_bytes()
    except Exception as exc:
        log_error(f"Failed to read {path}: {exc}")
        return None
    return _decode_bytes(raw)


def _extract_urls(text: str) -> set[str]:
    return set(URL_RE.findall(text))


# ---- Archive content extractors -------------------------------------------
def _extract_from_tar(path: Path) -> set[str]:
    urls: set[str] = set()
    try:
        with tarfile.open(path, "r:*") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                try:
                    fh = tar.extractfile(member)
                    if fh is None:
                        continue
                    urls |= _extract_urls(_decode_bytes(fh.read()))
                except Exception as exc:
                    log_warning(f"tar member {member.name} in {path}: {exc}")
    except Exception as exc:
        log_error(f"tar open {path}: {exc}")
    return urls


def _extract_from_zip(path: Path) -> set[str]:
    urls: set[str] = set()
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                try:
                    with zf.open(info) as fh:
                        urls |= _extract_urls(_decode_bytes(fh.read()))
                except Exception:
                    continue
    except Exception as exc:
        log_error(f"zip open {path}: {exc}")
    return urls


def _extract_from_7z(path: Path) -> set[str]:
    try:
        import py7zr  # type: ignore
    except ImportError:
        log_warning(f"py7zr not installed; skipping {path}")
        return set()
    urls: set[str] = set()
    try:
        with py7zr.SevenZipFile(path, mode="r") as zf:
            for bio in zf.readall().values():
                try:
                    urls |= _extract_urls(_decode_bytes(bio.read()))
                except Exception:
                    continue
    except Exception as exc:
        log_error(f"7z open {path}: {exc}")
    return urls


def _iter_files(root: Path, skip_dirs: set[str]) -> Iterable[Path]:
    """Yield files under *root* (or the file itself), skipping skip_dirs."""
    if root.is_file():
        yield root
        return
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in skip_dirs for part in p.parts):
            continue
        yield p


def _classify_git(url: str, git_hosts: tuple[str, ...]) -> bool:
    lower = url.lower()
    return any(h in lower for h in git_hosts)


# ---- Scan worker -----------------------------------------------------------
def _scan_worker(task: tuple) -> set[str]:
    """Multiprocessing worker: extract URLs from one file."""
    path_str, max_size, archives_only, files_only = task
    path = Path(path_str)
    urls: set[str] = set()
    try:
        size = path.stat().st_size
    except OSError:
        return urls
    if max_size and size > max_size:
        return urls

    kind = _archive_kind(path)
    if files_only and kind:
        return urls
    if archives_only and not kind:
        return urls

    if kind == "zip":
        urls |= _extract_from_zip(path)
    elif kind == "tar":
        urls |= _extract_from_tar(path)
    elif kind == "7z":
        urls |= _extract_from_7z(path)
    else:
        txt = _read_text_file(path)
        if txt:
            urls |= _extract_urls(txt)
    return urls


# ===========================================================================
# Subcommand: clean  (clean_urls.py)
# ===========================================================================
def cmd_clean(args: argparse.Namespace) -> int:
    """Dedupe domains; save github.com URLs separately."""
    domains: set[str] = set()
    git_urls: list[str] = []
    src = Path(args.input)
    if not src.exists():
        log_error(f"{src} not found")
        return 1
    with src.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                netloc = urlparse(line.strip()).netloc
            except Exception:
                print(line, end="")
                continue
            if netloc == "github.com":
                git_urls.append(line)
            domains.add(netloc)

    Path(args.domains_out).write_text(
        "".join(f"{d}\n" for d in domains),
        encoding="utf-8",
    )
    with Path(args.git_out).open("a", encoding="utf-8") as f:
        f.write("".join(git_urls))
    log_info(f"Wrote {len(domains)} domains -> {args.domains_out}")
    log_info(f"Appended {len(git_urls)} github URLs -> {args.git_out}")
    return 0


# ===========================================================================
# Subcommand: scan  (exlinks.py + furl.py + urlzz.py)
# ===========================================================================
def cmd_scan(args: argparse.Namespace) -> int:
    """Extract URLs from files and archives (recursively)."""
    inputs = [Path(p) for p in args.inputs] if args.inputs else [Path.cwd()]
    skip_dirs = {s for s in args.skip_dirs.split(",") if s}
    git_hosts = tuple(h for h in args.git_hosts.split(",") if h)

    files: list[Path] = []
    for inp in inputs:
        if not inp.exists():
            log_warning(f"Path does not exist: {inp}")
            continue
        files.extend(_iter_files(inp, skip_dirs))
    files = list(dict.fromkeys(files))
    if not files:
        log_info("No files to scan.")
        return 0

    log_info(f"Scanning {len(files)} files…")
    tasks = [
        (str(f), args.max_size, args.archives_only, args.files_only) for f in files
    ]

    all_urls: set[str] = set()
    if args.workers > 1 and len(tasks) > 1:
        with Pool(processes=args.workers) as pool:
            for result in _tqdm(
                pool.imap_unordered(_scan_worker, tasks),
                total=len(tasks),
                desc="Scanning",
            ):
                all_urls.update(result)
    else:
        for t in _tqdm(tasks, desc="Scanning"):
            all_urls.update(_scan_worker(t))

    git_urls = {u for u in all_urls if _classify_git(u, git_hosts)}
    main_urls = all_urls - git_urls if args.exclude_git_from_output else all_urls

    _write_urls(Path(args.output), sorted(main_urls), append=args.append)
    _write_urls(Path(args.git_output), sorted(git_urls), append=args.append)
    log_info(f"Wrote {len(main_urls)} URLs -> {args.output}")
    log_info(f"Wrote {len(git_urls)} git URLs -> {args.git_output}")
    return 0


# ===========================================================================
# Subcommand: split  (file_urls.py  +  split_urls.py)
# ===========================================================================
def _split_grouped(args: argparse.Namespace) -> int:
    """Original file_urls.py behavior."""
    group_map = {
        "html": (".html", ".htm"),
        "pdf": (".pdf",),
        "whl": (".whl",),
        "targz": (".tar.gz", ".tar.xz", ".tgz", ".txz"),
        "font": (".ttf", ".woff", ".woff2", ".eot", ".otf", ".ttc"),
        "js_css": (".js", ".css"),
    }
    src = Path(args.input)
    if not src.exists():
        log_error(f"{src} not found")
        return 1

    groups: dict[str, list[str]] = defaultdict(list)
    other: list[str] = []
    seen: set[str] = set()
    known_exts = tuple(e for exts in group_map.values() for e in exts)

    with src.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            url = line.strip()
            if not url or url in seen:
                continue
            seen.add(url)
            if not url.endswith(known_exts) and not url.endswith(args.file_exts):
                continue
            for gname, exts in group_map.items():
                if url.endswith(exts):
                    groups[gname].append(url)
                    break
            else:
                other.append(url)

    out_dir = Path(args.output_dir)
    for gname, urls in groups.items():
        if not urls:
            continue
        p = out_dir / f"{gname}_urls.txt"
        p.write_text("\n".join(urls), encoding="utf-8")
        log_info(f"{p.name}: {len(urls)} URLs")

    if other:
        Path(args.output).write_text(
            "\n".join(sorted(other)) + "\n",
            encoding="utf-8",
        )
        log_info(f"{args.output}: {len(other)} URLs")
    return 0


def _split_by_ext(args: argparse.Namespace) -> int:
    """Original split_urls.py behavior."""
    src = Path(args.input)
    if not src.exists():
        log_error(f"{src} not found")
        return 1

    buckets: dict[str, list[str]] = defaultdict(list)
    with src.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            url = line.strip().strip('"').strip("'")
            if not url:
                continue
            p = urlparse(url)
            name = (p.path or url).rstrip("/").split("/")[-1]
            if "." not in name:
                continue
            ext = name.rsplit(".", 1)[-1].lower()
            if ext in BY_EXT_KNOWN:
                buckets[ext].append(url)

    if not buckets:
        log_info("No URLs with recognized extensions found.")
        return 0
    out_dir = Path(args.output_dir)
    for ext, urls in sorted(buckets.items()):
        p = out_dir / f"{ext}_urls.txt"
        p.write_text("\n".join(urls) + "\n", encoding="utf-8")
        log_info(f"{p.name}: {len(urls)} URLs")
    return 0


def cmd_split(args: argparse.Namespace) -> int:
    args.file_exts = tuple(
        e if e.startswith(".") else "." + e for e in args.file_exts.split(",") if e
    )
    if args.mode == "grouped":
        return _split_grouped(args)
    return _split_by_ext(args)


# ===========================================================================
# Subcommand: filter-jscss  (filter_jscss_links.py)
# ===========================================================================
def cmd_filter_jscss(args: argparse.Namespace) -> int:
    pattern = re.compile(r"\.(min\.)?(js|css)$", re.IGNORECASE)
    src = Path(args.input)
    if not src.exists():
        log_error(f"{src} not found")
        return 1
    kept: list[str] = []
    seen: set[str] = set()
    with src.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            url = line.strip()
            if not url or url in seen:
                continue
            if pattern.search(urlparse(url).path):
                seen.add(url)
                kept.append(url)
    Path(args.output).write_text("\n".join(kept), encoding="utf-8")
    log_info(f"Kept {len(kept)} URLs -> {args.output}")
    return 0


# ===========================================================================
# Subcommand: prune  (process_urls.py + process_urls_aggresive.py)
# ===========================================================================
def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    try:
        p = urlparse(url)
    except ValueError:
        return ""
    scheme = p.scheme or "https"
    netloc = (p.netloc or "").lower()
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return f"{scheme}://{netloc}{path}"


def _url_root(url: str) -> str:
    p = urlparse(url)
    netloc = p.netloc.lower()
    parts = [s for s in p.path.split("/") if s]
    if netloc in ("github.com", "www.github.com"):
        if len(parts) >= 2:
            return f"https://github.com/{parts[0]}/{parts[1]}"
        return "https://github.com/"
    if not netloc:
        return url
    if not parts:
        return f"https://{netloc}/"
    return f"https://{netloc}/{parts[0]}"


def _prune_normal(urls: list[str]) -> list[str]:
    norm = {}
    for u in urls:
        n = _normalize_url(u)
        if n:
            norm[u] = n
    groups: dict[str, str] = {}
    for n in norm.values():
        root = _url_root(n)
        if root not in groups or len(n) < len(groups[root]):
            groups[root] = n
    candidates = sorted(groups.values(), key=len)
    result: list[str] = []
    for u in candidates:
        p = urlparse(u)
        netloc = p.netloc.lower()
        path = p.path.rstrip("/") or "/"
        prefix = path if path == "/" else path + "/"
        redundant = False
        for r in result:
            rp = urlparse(r)
            r_path = rp.path.rstrip("/") or "/"
            r_prefix = r_path if r_path == "/" else r_path + "/"
            if rp.netloc.lower() == netloc and prefix.startswith(r_prefix):
                redundant = True
                break
        if not redundant:
            result.append(u)
    result.sort()
    return result


def _prune_aggressive(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        n = _normalize_url(u)
        if not n:
            continue
        p = urlparse(n)
        netloc = p.netloc.lower()
        parts = [s for s in (p.path or "/").split("/") if s]
        if "github.com" in netloc:
            root = (
                f"https://github.com/{parts[0]}/{parts[1]}"
                if len(parts) >= 2
                else "https://github.com/"
            )
        else:
            root = f"https://{netloc}/"
        if root not in seen:
            seen.add(root)
            out.append(root)
    return sorted(out)


def cmd_prune(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.exists():
        log_error(f"{src} not found")
        return 1
    urls = [line.strip() for line in src.read_text(encoding="utf-8").splitlines()]
    urls = [u for u in urls if u]
    pruned = _prune_aggressive(urls) if args.aggressive else _prune_normal(urls)
    src.write_text("\n".join(pruned) + ("\n" if pruned else ""), encoding="utf-8")
    log_info(f"Pruned {len(urls)} -> {len(pruned)} URLs in {src}")
    return 0


# ===========================================================================
# Subcommand: move-gitlinks  (move_gitlinks.py)
# ===========================================================================
def cmd_move_gitlinks(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.exists():
        log_error(f"{src} not found")
        return 1
    lines = src.read_text(encoding="utf-8").splitlines()
    keep = [ln for ln in lines if "github.com" not in ln]
    moved = [ln for ln in lines if "github.com" in ln]

    with src.open("w", encoding="utf-8") as f:
        for ln in keep:
            f.write(f"{ln}\n")

    if not moved:
        log_info("No git links moved.")
        return 0

    out = Path(args.git_output)
    with out.open("a", encoding="utf-8") as f:
        f.write("\n")
        for ln in moved:
            f.write(f"{ln}\n")
    log_info(f"Moved {len(moved)} github lines -> {out}")
    return 0


# ===========================================================================
# Subcommand: save-page  (saveurl.py)
# ===========================================================================
def cmd_save_page(args: argparse.Namespace) -> int:
    try:
        from pywebcopy import save_webpage  # type: ignore
    except ImportError:
        log_error("pywebcopy is required for save-page (pip install pywebcopy)")
        return 1
    save_webpage(
        url=args.url,
        project_folder=args.project_folder,
        project_name=args.project_name or args.url,
        bypass_robots=args.bypass_robots,
        debug=args.debug,
        open_in_browser=args.open_in_browser,
        delay=None,
        threaded=False,
    )
    return 0


# ===========================================================================
# Subcommand: fetch-files  (xfile_urls.py)
# ===========================================================================
def _strip_url_punct(url: str) -> str:
    return url.strip().strip("\"'<>(),;")


def _has_fetch_ext(url: str) -> bool:
    try:
        path = unquote(urlparse(url).path).lower()
        return any(path.endswith(e) for e in FETCH_EXTS)
    except ValueError:
        return False


def _download_filename(url: str) -> str:
    p = urlparse(url)
    name = os.path.basename(unquote(p.path)) or "downloaded_file"
    stem, ext = os.path.splitext(name)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    safe_stem = re.sub(r"[^A-Za-z0-9._-]", "_", stem)
    return f"{safe_stem}_{digest}{ext}"


def _download_one(task: tuple) -> tuple[str, bool, str]:
    try:
        import requests  # type: ignore
    except ImportError:
        return task[0], False, "requests not installed"
    url, dest_dir = task
    dest = Path(dest_dir) / _download_filename(url)
    try:
        r = requests.get(
            url,
            timeout=30,
            allow_redirects=True,
            headers={"User-Agent": "urlkit/1.0"},
        )
        r.raise_for_status()
        dest.write_bytes(r.content)
        return url, True, str(dest)
    except Exception as exc:
        return url, False, str(exc)


def cmd_fetch_files(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.exists():
        log_error(f"{src} not found")
        return 1

    found: set[str] = set()
    with src.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            for raw in URL_RE.findall(line):
                url = _strip_url_punct(raw)
                if _has_fetch_ext(url):
                    found.add(url)

    out_urls = sorted(found)
    Path(args.output).write_text(
        "\n".join(out_urls) + ("\n" if out_urls else ""), encoding="utf-8"
    )
    log_info(f"Extracted {len(out_urls)} matching URLs -> {args.output}")

    if args.download and out_urls:
        dest = Path(args.download)
        dest.mkdir(parents=True, exist_ok=True)
        tasks = [(u, str(dest)) for u in out_urls]
        if args.workers > 1:
            with Pool(processes=args.workers) as pool:
                for url, ok, info in pool.imap_unordered(_download_one, tasks):
                    print(f"[{'OK' if ok else 'FAIL'}] {url} -> {info}")
        else:
            for t in tasks:
                url, ok, info = _download_one(t)
                print(f"[{'OK' if ok else 'FAIL'}] {url} -> {info}")
    return 0


# ===========================================================================
# CLI
# ===========================================================================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="urlkit",
        description="Unified URL extraction / cleaning toolkit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Original → merged mapping")[1]
        if "Original → merged mapping" in __doc__
        else None,
    )
    sub = p.add_subparsers(dest="command", required=True)

    # --- clean ---------------------------------------------------------
    pc = sub.add_parser("clean", help="Dedupe domains; split github URLs.")
    pc.add_argument("--input", default="urls.txt")
    pc.add_argument("--domains-out", default="cleaned_urls")
    pc.add_argument("--git-out", default="git_urls")
    pc.set_defaults(func=cmd_clean)

    # --- scan ----------------------------------------------------------
    ps = sub.add_parser(
        "scan",
        help="Extract URLs from files/archives (exlinks + furl + urlzz).",
    )
    ps.add_argument("inputs", nargs="*", help="Files/dirs to scan (default: cwd).")
    ps.add_argument("-o", "--output", default="urls.txt")
    ps.add_argument("-g", "--git-output", default="gitlinks.txt")
    ps.add_argument("-w", "--workers", type=int, default=8)
    ps.add_argument(
        "--append",
        action="store_true",
        help="Append to outputs instead of overwriting (urlzz.py behavior).",
    )
    ps.add_argument(
        "--archives-only",
        action="store_true",
        help="Only read archives (exlinks.py behavior).",
    )
    ps.add_argument(
        "--files-only", action="store_true", help="Skip archives, only read text files."
    )
    ps.add_argument(
        "--max-size",
        type=int,
        default=10 * 1024 * 1024,
        help="Skip files larger than this many bytes (0 = no limit).",
    )
    ps.add_argument("--skip-dirs", default=DEFAULT_SKIP_DIRS)
    ps.add_argument("--git-hosts", default=DEFAULT_GIT_HOSTS)
    ps.add_argument(
        "--exclude-git-from-output",
        action="store_true",
        help="Remove git-host URLs from the main output (furl.py behavior).",
    )
    ps.set_defaults(func=cmd_scan)

    # --- split ---------------------------------------------------------
    psp = sub.add_parser(
        "split",
        help="Split URLs by group or by file extension (file_urls + split_urls).",
    )
    psp.add_argument("-i", "--input", default="urls.txt")
    psp.add_argument(
        "-o", "--output", default="file_urls.txt", help="'Other' bucket (grouped mode)."
    )
    psp.add_argument("--output-dir", default=".")
    psp.add_argument(
        "--mode",
        choices=("grouped", "by-ext"),
        default="grouped",
        help="'grouped' = file_urls.py buckets; "
        "'by-ext' = split_urls.py per-extension files.",
    )
    psp.add_argument(
        "--file-exts",
        default=DEFAULT_FILE_EXTS,
        help="Comma-separated extensions considered when deciding "
        "which URLs to keep in grouped mode.",
    )
    psp.set_defaults(func=cmd_split)

    # --- filter-jscss --------------------------------------------------
    pj = sub.add_parser(
        "filter-jscss", help="Keep only .js/.css URLs (filter_jscss_links.py)."
    )
    pj.add_argument("-i", "--input", default="urls.txt")
    pj.add_argument("-o", "--output", default="filtered_urls.txt")
    pj.set_defaults(func=cmd_filter_jscss)

    # --- prune ---------------------------------------------------------
    pp = sub.add_parser(
        "prune",
        help="Normalize and prune redundant URLs "
        "(process_urls + process_urls_aggresive).",
    )
    pp.add_argument("-i", "--input", default="urls.txt")
    pp.add_argument(
        "--aggressive",
        action="store_true",
        help="Collapse every URL to its root (process_urls_aggresive.py).",
    )
    pp.set_defaults(func=cmd_prune)

    # --- move-gitlinks -------------------------------------------------
    pm = sub.add_parser(
        "move-gitlinks",
        help="Move github.com lines from a file into gitlinks.txt (move_gitlinks.py).",
    )
    pm.add_argument("input")
    pm.add_argument("-g", "--git-output", default="gitlinks.txt")
    pm.set_defaults(func=cmd_move_gitlinks)

    # --- save-page -----------------------------------------------------
    psv = sub.add_parser(
        "save-page", help="Save a webpage with pywebcopy (saveurl.py)."
    )
    psv.add_argument("url")
    psv.add_argument("--project-folder", default="./saved_pages/")
    psv.add_argument(
        "--project-name",
        default=None,
        help="Defaults to the URL string (saveurl.py behavior).",
    )
    psv.add_argument("--bypass-robots", action="store_true", default=True)
    psv.add_argument("--no-bypass-robots", dest="bypass_robots", action="store_false")
    psv.add_argument("--debug", action="store_true", default=True)
    psv.add_argument("--no-debug", dest="debug", action="store_false")
    psv.add_argument("--open-in-browser", action="store_true", default=True)
    psv.add_argument(
        "--no-open-in-browser", dest="open_in_browser", action="store_false"
    )
    psv.set_defaults(func=cmd_save_page)

    # --- fetch-files ---------------------------------------------------
    pf = sub.add_parser(
        "fetch-files",
        help="Extract css/font/pdf URLs and optionally download them (xfile_urls.py).",
    )
    pf.add_argument("-i", "--input", default="urls.txt")
    pf.add_argument("-o", "--output", default="file_urls.txt")
    pf.add_argument(
        "-d",
        "--download",
        nargs="?",
        const="downloads",
        default=None,
        metavar="DIR",
        help="Download matching files into DIR (default: downloads).",
    )
    pf.add_argument("-w", "--workers", type=int, default=os.cpu_count() or 4)
    pf.set_defaults(func=cmd_fetch_files)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "workers", 1) is not None and getattr(args, "workers", 1) < 1:
        parser.error("--workers must be at least 1")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
