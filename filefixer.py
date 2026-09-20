#!/data/data/com.termux/files/home/.local/bin/python
"""
filefixer.py — merged extension-fixing / validation / Python-line extraction tool.

Original scripts merged here:
  fix_ext.py
  fix_extension_mismatch_Version1.py
  fix_extension_mismatch_Version2.py
  fixext.py
  fixext2.py
  fixext3.py
  fixfileext.py
  fpy.py
  validate_binary_extensions.py
  validate_text_extensions.py

Usage examples:
  python filefixer.py fix . --apply --engines auto --workers 4
  python filefixer.py fix . --scan-cwd --engines puremagic --apply
  python filefixer.py fix . --engines signature --dry-run
  python filefixer.py validate binary /data/data/com.termux --workers 4
  python filefixer.py validate text . --workers 4
  python filefixer.py extract-python some_file.py -o out.py

Optional third-party packages:
  pip install puremagic python-magic filetype
"""

from __future__ import annotations

import argparse
import concurrent.futures
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tokenize
import zipfile
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from io import StringIO
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Optional dependencies and dh fallbacks
# ---------------------------------------------------------------------------

try:
    import puremagic  # type: ignore
except Exception:  # pragma: no cover
    puremagic = None  # type: ignore

try:
    import magic  # type: ignore
except Exception:  # pragma: no cover
    magic = None  # type: ignore

try:
    import filetype  # type: ignore
except Exception:  # pragma: no cover
    filetype = None  # type: ignore

try:
    from dh import (  # type: ignore
        BIN_EXT as DH_BIN_EXT,
        MIME2EXT as DH_MIME2EXT,
        SHEBANG_MAP as DH_SHEBANG_MAP,
        TXT_EXT as DH_TXT_EXT,
        get_files as dh_get_files,
        is_binary as dh_is_binary,
    )
except Exception:  # pragma: no cover
    DH_BIN_EXT = None
    DH_MIME2EXT = None
    DH_SHEBANG_MAP = None
    DH_TXT_EXT = None
    dh_get_files = None
    dh_is_binary = None

# ---------------------------------------------------------------------------
# Built-in maps / constants
# ---------------------------------------------------------------------------

ALIASES: dict[str, str] = {
    ".jpeg": ".jpg",
    ".tiff": ".tif",
    ".htm": ".html",
    ".tgz": ".tar.gz",
}

COMPOUND_EXTS: tuple[str, ...] = (
    ".tar.gz",
    ".tar.bz2",
    ".tar.xz",
    ".min.js",
    ".min.css",
)

MIME2EXT: dict[str, str | list[str]] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/tiff": ".tif",
    "image/x-tiff": ".tif",
    "image/bmp": ".bmp",
    "image/x-ms-bmp": ".bmp",
    "image/x-icon": ".ico",
    "image/svg+xml": ".svg",
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/x-tar": ".tar",
    "application/gzip": ".gz",
    "application/x-gzip": ".gz",
    "application/x-bzip2": ".bz2",
    "application/x-7z-compressed": ".7z",
    "application/x-rar": ".rar",
    "application/x-rar-compressed": ".rar",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "audio/mpeg": ".mp3",
    "audio/x-mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/ogg": ".ogg",
    "audio/x-ogg": ".ogg",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/aac": ".aac",
    "audio/x-m4a": ".m4a",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
    "video/x-matroska": ".mkv",
    "video/webm": ".webm",
    "video/x-flv": ".flv",
    "video/x-ms-wmv": ".wmv",
    "video/x-m4v": ".m4v",
    "text/plain": ".txt",
    "text/html": ".html",
    "application/json": ".json",
    "text/json": ".json",
    "text/xml": ".xml",
    "application/xml": ".xml",
    "text/csv": ".csv",
    "text/markdown": ".md",
    "text/x-python": ".py",
    "text/x-shellscript": ".sh",
    "text/javascript": ".js",
    "application/javascript": ".js",
    "application/x-elf": ".elf",
    "application/x-executable": ".elf",
    "application/x-sharedlib": ".so",
    "application/x-dosexec": ".exe",
    "application/x-pe-executable": ".exe",
    "application/octet-stream": "",
}

if DH_MIME2EXT:
    MIME2EXT.update(DH_MIME2EXT)  # type: ignore[arg-type]

SHEBANG_MAP: dict[str, str] = {
    "python": ".py",
    "python3": ".py",
    "sh": ".sh",
    "bash": ".sh",
    "zsh": ".zsh",
    "perl": ".pl",
    "ruby": ".rb",
    "node": ".js",
    "php": ".php",
    "lua": ".lua",
}
if DH_SHEBANG_MAP:
    SHEBANG_MAP.update(DH_SHEBANG_MAP)  # type: ignore[arg-type]

BIN_EXT: set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
    ".pdf",
    ".zip",
    ".gz",
    ".bz2",
    ".7z",
    ".rar",
    ".tar",
    ".mp3",
    ".mp4",
    ".mkv",
    ".wav",
    ".ogg",
    ".flac",
    ".elf",
    ".exe",
    ".so",
    ".dll",
    ".class",
    ".pyc",
    ".whl",
    ".xz",
}
if DH_BIN_EXT:
    BIN_EXT = set(DH_BIN_EXT)

TXT_EXT: set[str] = {
    ".txt",
    ".md",
    ".py",
    ".js",
    ".html",
    ".htm",
    ".css",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".csv",
    ".ini",
    ".cfg",
    ".sh",
    ".c",
    ".h",
    ".cpp",
    ".java",
    ".rs",
    ".go",
    ".rb",
    ".php",
    ".sql",
    ".log",
}
if DH_TXT_EXT:
    TXT_EXT = set(DH_TXT_EXT)

DEFAULT_PROTECT_EXT: set[str] = {
    ".py",
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".java",
    ".rs",
    ".go",
    ".rb",
    ".js",
    ".ts",
    ".css",
    ".min.js",
    ".min.css",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
}

DEFAULT_IGNORE_EXT: set[str] = set()

# Built-in magic signatures from V1/V2.
SIGNATURES: list[tuple[Callable[[bytes], bool], str, str]] = [
    (lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"), ".png", "PNG image"),
    (lambda b: b.startswith(b"\xff\xd8\xff"), ".jpg", "JPEG image"),
    (lambda b: b.startswith((b"GIF87a", b"GIF89a")), ".gif", "GIF image"),
    (lambda b: b.startswith(b"BM"), ".bmp", "BMP image"),
    (
        lambda b: b.startswith((b"II*\x00", b"I\x00*\x00", b"MM\x00*")),
        ".tif",
        "TIFF image",
    ),
    (lambda b: b.startswith(b"WEBP"), ".webp", "WebP image"),
    (lambda b: b.startswith(b"%PDF-"), ".pdf", "PDF document"),
    (
        lambda b: b.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")),
        ".zip",
        "ZIP archive",
    ),
    (lambda b: b.startswith(b"\x1f\x8b\x08"), ".gz", "GZIP compressed"),
    (lambda b: b.startswith(b"BZh"), ".bz2", "BZIP2 compressed"),
    (lambda b: b.startswith(b"7z\xbc\xaf'\x1c"), ".7z", "7-Zip archive"),
    (lambda b: b.startswith(b"Rar!\x1a\x07\x00"), ".rar", "RAR archive"),
    (lambda b: len(b) > 262 and b[257:262] == b"ustar", ".tar", "TAR archive"),
    (
        lambda b: (
            b.startswith(b"ID3") or (len(b) >= 2 and b[0] == 255 and b[1] & 224 == 224)
        ),
        ".mp3",
        "MP3 audio",
    ),
    (lambda b: len(b) > 8 and b[4:8] == b"ftyp", ".mp4", "MP4/ISO-BMFF"),
    (lambda b: b.startswith(b"\x1aE\xdf\xa3"), ".mkv", "Matroska (MKV/WebM)"),
    (
        lambda b: b.startswith(b"RIFF") and len(b) > 8 and b[8:12] == b"WAVE",
        ".wav",
        "WAV audio",
    ),
    (lambda b: b.startswith(b"OggS"), ".ogg", "OGG container"),
    (lambda b: b.startswith(b"fLaC"), ".flac", "FLAC audio"),
    (
        lambda b: (
            b.lstrip().startswith(b"<")
            and (
                b.lstrip()[:10].lower().startswith(b"<!doctype")
                or b.lstrip()[:6].lower().startswith(b"<html")
            )
        ),
        ".html",
        "HTML document",
    ),
    (
        lambda b: b.lstrip().startswith(b"{") or b.lstrip().startswith(b"["),
        ".json",
        "JSON-ish text",
    ),
    (lambda b: b.startswith(b"\x7fELF"), ".elf", "ELF binary"),
    (lambda b: b.startswith(b"MZ"), ".exe", "PE/EXE binary"),
]

# `file -b` description mapping from fixext3.
FILE_DESC2EXT: dict[str, str] = {
    "xz compressed data": ".xz",
    "jpeg image data": ".jpg",
    "png image data": ".png",
    "gif image data": ".gif",
    "tiff image data": ".tiff",
    "bitmap image data": ".bmp",
    "svg image data": ".svg",
    "pdf document": ".pdf",
    "microsoft word document": ".doc",
    "microsoft office document": ".docx",
    "excel spreadsheet": ".xls",
    "microsoft excel (openxml) spreadsheet": ".xlsx",
    "powerpoint presentation": ".ppt",
    "microsoft powerpoint (openxml) presentation": ".pptx",
    "zip archive data": ".zip",
    "gzip compressed data": ".gz",
    "tar archive data": ".tar",
    "bzip2 compressed data": ".bz2",
    "shared object (linux)": ".so",
    "python script": ".py",
    "javascript (ecmascript)": ".js",
    "html document": ".html",
    "xml document": ".xml",
    "json data": ".json",
    "c source, ascii text": ".c",
    "c++ source, ascii text": ".cpp",
    "makefile": ".mk",
    "ascii text": ".txt",
    "utf-8 unicode text": ".txt",
    "iso-8859 text": ".txt",
    "data": ".bin",
    "java class file": ".class",
    "executable file": ".exe",
    "elf 64-bit lsb executable": ".elf",
    "mach-o executable": ".dylib",
    "wave sound data": ".wav",
    "mpeg audio": ".mp3",
}

LOG = logging.getLogger("filefixer")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Detection:
    """A detected file type."""

    ext: str
    desc: str
    engine: str
    mime: str | None = None


@dataclass
class FixResult:
    """Result of processing one file in `fix` mode."""

    path: Path
    action: str
    current_ext: str | None = None
    detected_ext: str | None = None
    detected_desc: str | None = None
    target: Path | None = None
    reason: str | None = None
    engine: str | None = None


# ---------------------------------------------------------------------------
# Basic helpers
# ---------------------------------------------------------------------------


def eprint(*args: Any, **kwargs: Any) -> None:
    """Print to stderr."""
    print(*args, file=sys.stderr, **kwargs)


def norm_ext(ext: str | None) -> str:
    """Normalize an extension to lower-case with a leading dot."""
    if not ext:
        return ""
    ext = str(ext).strip().lower()
    if not ext:
        return ""
    if not ext.startswith("."):
        ext = "." + ext
    return ALIASES.get(ext, ext)


def parse_ext_set(value: str | None) -> set[str]:
    """Parse a comma-separated extension list into a normalized set."""
    if not value:
        return set()
    return {norm_ext(part) for part in value.split(",") if part.strip()}


def parse_engine_list(value: str | None) -> list[str]:
    """Parse engine selection string."""
    if not value or value.lower() == "auto":
        return [
            "shebang",
            "puremagic",
            "magic",
            "filetype",
            "file-mime",
            "signature",
            "mimetypes",
            "text",
        ]
    engines = [x.strip().lower() for x in value.split(",") if x.strip()]
    allowed = {
        "shebang",
        "puremagic",
        "magic",
        "filetype",
        "file-mime",
        "file-b",
        "signature",
        "mimetypes",
        "text",
    }
    bad = [x for x in engines if x not in allowed]
    if bad:
        raise argparse.ArgumentTypeError(f"Unknown engine(s): {', '.join(bad)}")
    return engines


def current_ext(path: Path) -> str:
    """Return the effective extension, respecting compound suffixes."""
    name = path.name.lower()
    for ext in COMPOUND_EXTS:
        if name.endswith(ext):
            return ext
    return path.suffix.lower()


def mime_to_ext(mime: str | None) -> str | None:
    """Map a MIME type to an extension."""
    if not mime:
        return None
    mime = mime.lower().split(";", 1)[0].strip()
    value = MIME2EXT.get(mime)
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        value = MIME2EXT.get(mime.split("/", 1)[0] + "/*")
    if isinstance(value, list):
        value = value[0] if value else None
    return norm_ext(value) if value else None


def desc_to_ext(desc: str | None) -> str | None:
    """Map `file -b` description text to an extension."""
    if not desc:
        return None
    key = desc.lower().strip().rstrip(".,")
    if key in FILE_DESC2EXT:
        return norm_ext(FILE_DESC2EXT[key])
    for needle, ext in FILE_DESC2EXT.items():
        if needle in key:
            return norm_ext(ext)
    if "text" in key:
        return ".txt"
    return None


def is_binary_file(path: Path, sample_size: int = 8192) -> bool | None:
    """Return True if binary, False if text, None on access error."""
    try:
        with path.open("rb") as fh:
            data = fh.read(sample_size)
    except (OSError, PermissionError):
        return None
    if not data:
        return False
    if b"\x00" in data:
        return True
    try:
        data.decode("utf-8")
        return False
    except UnicodeDecodeError:
        for enc in ("latin-1", "iso-8859-1", "cp1252"):
            try:
                data.decode(enc)
                return False
            except (UnicodeDecodeError, LookupError):
                continue
        return True


# ---------------------------------------------------------------------------
# File walking
# ---------------------------------------------------------------------------


def iter_files(
    root: Path,
    *,
    recursive: bool = True,
    skip_hidden: bool = True,
    follow_symlinks: bool = False,
    skip_mount_points: bool = False,
) -> Iterator[Path]:
    """Yield files under root according to traversal options."""
    if root.is_file():
        yield root
        return

    if not root.is_dir():
        return

    root_dev: int | None = None
    if skip_mount_points:
        try:
            root_dev = root.stat().st_dev
        except OSError:
            root_dev = None

    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        if skip_hidden:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]

        if skip_mount_points and root_dev is not None:
            try:
                if Path(dirpath).stat().st_dev != root_dev:
                    dirnames[:] = []
                    continue
            except OSError:
                dirnames[:] = []
                continue

        for filename in filenames:
            if skip_hidden and filename.startswith("."):
                continue
            path = Path(dirpath) / filename
            if path.is_file():
                yield path

        if not recursive:
            break


def collect_files(
    paths: Sequence[str],
    *,
    recursive: bool = True,
    skip_hidden: bool = True,
    follow_symlinks: bool = False,
    skip_mount_points: bool = False,
) -> list[Path]:
    """Collect unique files from multiple file/directory paths."""
    files: list[Path] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(
                iter_files(
                    path,
                    recursive=recursive,
                    skip_hidden=skip_hidden,
                    follow_symlinks=follow_symlinks,
                    skip_mount_points=skip_mount_points,
                )
            )
        else:
            eprint(f"Warning: not found or unsupported: {path}")
    return list(dict.fromkeys(files))


# ---------------------------------------------------------------------------
# Detection engines
# ---------------------------------------------------------------------------


def detect_signature(path: Path, sample_size: int = 8192) -> Detection | None:
    """Built-in signature detector from V1/V2."""
    try:
        with path.open("rb") as fh:
            data = fh.read(sample_size)
    except (OSError, PermissionError):
        return None

    for matcher, ext, desc in SIGNATURES:
        try:
            if matcher(data):
                return Detection(norm_ext(ext), desc, "signature")
        except Exception:
            continue

    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path, "r") as zf:
                for name in zf.namelist():
                    if name.endswith(".dist-info/"):
                        return Detection(".whl", "Python wheel (zip)", "signature")
                    if name.endswith(".egg-info/"):
                        return Detection(".zip", "Python egg archive", "signature")
            return Detection(".zip", "ZIP archive", "signature")
    except Exception:
        pass

    try:
        if tarfile.is_tarfile(path):
            if path.name.lower().endswith((".tar.gz", ".tgz")):
                return Detection(".tar.gz", "TAR.GZ archive", "signature")
            return Detection(".tar", "TAR archive", "signature")
    except Exception:
        pass

    try:
        with path.open("rb") as fh:
            data = fh.read(1024)
        if data:
            printable = sum(1 for c in data if 32 <= c <= 126 or c in (9, 10, 13))
            if printable / max(1, len(data)) > 0.9:
                return Detection(".txt", "Plain text (heuristic)", "signature")
    except Exception:
        pass

    return None


def detect_puremagic(path: Path) -> Detection | None:
    """Detect with puremagic, if installed."""
    if puremagic is None:
        return None
    try:
        matches = puremagic.magic_string(path.read_bytes())
    except Exception:
        return None
    if not matches:
        return None
    match = matches[0]
    ext = getattr(match, "extension", "") or ""
    mime = getattr(match, "mime_type", "") or ""
    if ext:
        return Detection(norm_ext(ext), f"puremagic: {match}", "puremagic", mime)
    mapped = mime_to_ext(mime)
    if mapped:
        return Detection(mapped, f"puremagic MIME: {mime}", "puremagic", mime)
    return None


def detect_magic(path: Path) -> Detection | None:
    """Detect with python-magic, if installed."""
    if magic is None:
        return None
    try:
        mime = magic.Magic(mime=True).from_file(str(path))
        ext = mime_to_ext(mime)
        if ext:
            return Detection(ext, f"python-magic MIME: {mime}", "magic", mime)
    except Exception:
        return None
    return None


def detect_filetype(path: Path) -> Detection | None:
    """Detect with filetype, if installed."""
    if filetype is None:
        return None
    try:
        kind = filetype.guess(str(path))
        if kind:
            return Detection(
                norm_ext(f".{kind.extension}"),
                f"filetype: {kind.mime}",
                "filetype",
                kind.mime,
            )
    except Exception:
        return None
    return None


def detect_file_mime(path: Path) -> Detection | None:
    """Detect with `file --brief --mime-type`."""
    try:
        out = subprocess.check_output(
            ["file", "--brief", "--mime-type", str(path)],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
    except Exception:
        return None
    ext = mime_to_ext(out)
    if ext:
        return Detection(ext, f"file MIME: {out}", "file-mime", out)
    return None


def detect_file_b(path: Path) -> Detection | None:
    """Detect with `file -b` description mapping."""
    try:
        out = subprocess.check_output(
            ["file", "-b", str(path)],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
    except Exception:
        return None
    ext = desc_to_ext(out)
    if ext:
        return Detection(ext, f"file: {out}", "file-b")
    return None


def detect_shebang(path: Path) -> Detection | None:
    """Detect interpreter from a shebang line."""
    try:
        with path.open("rb") as fh:
            first = fh.readline()
    except (OSError, PermissionError):
        return None
    if not first.startswith(b"#!"):
        return None
    try:
        line = first.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None
    parts = line.split()
    if len(parts) < 2:
        return None
    interp = Path(parts[1]).name
    if "env" in interp and len(parts) >= 3:
        interp = Path(parts[2]).name
    for key, ext in SHEBANG_MAP.items():
        if key in interp or interp in key:
            return Detection(norm_ext(ext), f"shebang: {line}", "shebang")
    return None


def detect_mimetypes(path: Path) -> Detection | None:
    """Detect using stdlib mimetypes."""
    mime, _ = mimetypes.guess_type(str(path))
    ext = mime_to_ext(mime)
    if ext:
        return Detection(ext, f"mimetypes: {mime}", "mimetypes", mime)
    return None


def guess_text_extension(text: str) -> str | None:
    """Heuristic text subtype detection from fixext2/fpy."""
    text = text.strip()
    if not text:
        return None
    if text.startswith("#!") and "python" in text:
        return ".py"
    if any(
        token in text for token in ("def ", "class ", "import ", "from ", "__main__")
    ):
        return ".py"
    if text.startswith("#!") and ("sh" in text or "bash" in text):
        return ".sh"
    if text.startswith(("# ", "## ")) or "---" in text:
        return ".md"
    if text.startswith("---") or (": " in text and "\n" in text):
        return ".yaml"
    if "=" in text and "[" in text and "]" in text:
        return ".toml"
    if text.startswith("[") and "]" in text:
        return ".ini"
    if any(
        text.lower().startswith(cmd)
        for cmd in ("select ", "insert ", "update ", "delete ", "create ")
    ):
        return ".sql"
    if "{" in text and "}" in text and ":" in text:
        return ".css"
    if "," in text and "\n" in text:
        return ".csv"
    if text.startswith("<?xml"):
        return ".xml"
    return None


def detect_text(path: Path) -> Detection | None:
    """Heuristic text detector from fixext2/fixext."""
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            sample = fh.read(4096)
    except Exception:
        return None
    ext = guess_text_extension(sample)
    if ext:
        return Detection(norm_ext(ext), "text heuristic", "text")
    if sample:
        printable = sum(1 for c in sample if 32 <= ord(c) <= 126 or c in "\t\n\r")
        if printable / max(1, len(sample)) > 0.9:
            return Detection(".txt", "plain text heuristic", "text")
    return None


DETECTORS: dict[str, Callable[[Path], Detection | None]] = {
    "signature": detect_signature,
    "puremagic": detect_puremagic,
    "magic": detect_magic,
    "filetype": detect_filetype,
    "file-mime": detect_file_mime,
    "file-b": detect_file_b,
    "shebang": detect_shebang,
    "mimetypes": detect_mimetypes,
    "text": detect_text,
}


def detect_extension(
    path: Path, engines: Sequence[str], *, debug: bool = False
) -> Detection | None:
    """Try detection engines in order and return the first successful result."""
    for engine in engines:
        detector = DETECTORS.get(engine)
        if not detector:
            continue
        try:
            detection = detector(path)
        except Exception as exc:
            if debug:
                LOG.debug("Engine %s failed for %s: %s", engine, path, exc)
            continue
        if detection and detection.ext:
            return detection
    return None


# ---------------------------------------------------------------------------
# Rename helpers
# ---------------------------------------------------------------------------


def rename_with_policy(
    src: Path,
    dst: Path,
    collision: str,
) -> tuple[Path, bool, str | None]:
    """
    Rename src to dst using the requested collision policy.

    Returns (final_path, renamed, error_message).
    """
    if src == dst:
        return src, False, "target equals source"

    if collision == "overwrite":
        try:
            if dst.exists():
                dst.unlink()
            src.rename(dst)
            return dst, True, None
        except OSError as exc:
            return src, False, str(exc)

    if not dst.exists():
        try:
            src.rename(dst)
            return dst, True, None
        except OSError:
            try:
                shutil.move(str(src), str(dst))
                return dst, True, None
            except Exception as exc:
                return src, False, str(exc)

    if collision == "skip":
        return src, False, "target exists"

    parent = dst.parent
    stem = dst.stem
    suffix = dst.suffix

    for i in range(1, 1000):
        if collision == "parenthesized":
            candidate = parent / f"{stem} ({i}){suffix}"
        else:
            candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            try:
                src.rename(candidate)
                return candidate, True, None
            except OSError:
                try:
                    shutil.move(str(src), str(candidate))
                    return candidate, True, None
                except Exception as exc:
                    return src, False, str(exc)

    return src, False, "failed to find non-conflicting name"


# ---------------------------------------------------------------------------
# Fix mode
# ---------------------------------------------------------------------------


def process_fix_file(
    path: Path,
    *,
    engines: Sequence[str],
    apply: bool,
    collision: str,
    protect_ext: set[str],
    ignore_ext: set[str],
    force_protected: bool,
    skip_text_mismatches: bool,
    debug: bool,
) -> FixResult:
    """Process one file for extension mismatch."""
    current = current_ext(path)

    if current in ignore_ext:
        return FixResult(
            path, "skipped", current_ext=current, reason=f"ignored extension {current}"
        )

    detection = detect_extension(path, engines, debug=debug)
    if not detection:
        return FixResult(path, "skipped", current_ext=current, reason="unknown type")

    detected = norm_ext(detection.ext)
    if not detected:
        return FixResult(
            path, "skipped", current_ext=current, reason="empty detected extension"
        )

    if current == detected:
        return FixResult(
            path,
            "ok",
            current_ext=current,
            detected_ext=detected,
            detected_desc=detection.desc,
            engine=detection.engine,
        )

    if current in protect_ext and not force_protected:
        return FixResult(
            path,
            "skipped",
            current_ext=current,
            detected_ext=detected,
            detected_desc=detection.desc,
            reason=f"protected extension {current}",
            engine=detection.engine,
        )

    if skip_text_mismatches and detected == ".txt" and current in TXT_EXT:
        return FixResult(
            path,
            "skipped",
            current_ext=current,
            detected_ext=detected,
            detected_desc=detection.desc,
            reason="text-to-text mismatch skipped",
            engine=detection.engine,
        )

    name = path.name
    if current and name.lower().endswith(current):
        base = name[: -len(current)]
    else:
        base = path.stem
    target = path.with_name(base + detected)

    if target == path:
        return FixResult(
            path,
            "skipped",
            current_ext=current,
            detected_ext=detected,
            detected_desc=detection.desc,
            reason="target equals source",
            engine=detection.engine,
        )

    if not apply:
        return FixResult(
            path,
            "would-rename",
            current_ext=current,
            detected_ext=detected,
            detected_desc=detection.desc,
            target=target,
            engine=detection.engine,
        )

    final, renamed, error = rename_with_policy(path, target, collision)
    if renamed:
        return FixResult(
            path,
            "renamed",
            current_ext=current,
            detected_ext=detected,
            detected_desc=detection.desc,
            target=final,
            engine=detection.engine,
        )
    return FixResult(
        path,
        "error",
        current_ext=current,
        detected_ext=detected,
        detected_desc=detection.desc,
        target=target,
        reason=error,
        engine=detection.engine,
    )


def run_fix_pass(
    files: Sequence[Path], args: argparse.Namespace, *, apply: bool
) -> list[FixResult]:
    """Run one fix pass over files."""
    engines = parse_engine_list(args.engines)
    protect_ext = set() if args.no_protect else parse_ext_set(args.protect_ext)
    ignore_ext = parse_ext_set(args.ignore_ext)

    results: list[FixResult] = []
    workers = max(1, args.workers)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                process_fix_file,
                path,
                engines=engines,
                apply=apply,
                collision=args.collision,
                protect_ext=protect_ext,
                ignore_ext=ignore_ext,
                force_protected=args.force_protected,
                skip_text_mismatches=args.skip_text_mismatches,
                debug=args.debug,
            )
            for path in files
        ]
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                eprint(f"Error processing file: {exc}")
    return results


def print_fix_summary(results: Sequence[FixResult], *, verbose: bool) -> None:
    """Print fix summary."""
    renamed = [r for r in results if r.action == "renamed"]
    would = [r for r in results if r.action == "would-rename"]
    skipped = [r for r in results if r.action in {"skipped", "ok"}]
    errors = [r for r in results if r.action == "error"]

    if verbose:
        for result in results:
            if result.action in {"would-rename", "renamed"}:
                print(
                    f"{result.action}: {result.path} -> {result.target} ({result.detected_desc})"
                )
            elif result.action == "ok":
                print(f"ok: {result.path} (already matched)")
            else:
                print(f"{result.action}: {result.path} ({result.reason})")

    print()
    print("Summary:")
    print(f"  files scanned: {len(results)}")
    print(f"  would-rename (dry-run): {len(would)}")
    print(f"  renamed: {len(renamed)}")
    print(f"  skipped/ok: {len(skipped)}")
    print(f"  errors: {len(errors)}")

    if errors:
        print("\nErrors:")
        for result in errors[:10]:
            print(f"  {result.path}: {result.reason}")


def cmd_fix(args: argparse.Namespace) -> int:
    """CLI handler for `fix`."""
    if args.scan_cwd:
        paths = [str(Path.cwd())]
    else:
        paths = args.paths or ["."]

    files = collect_files(
        paths,
        recursive=not args.no_recursive,
        skip_hidden=not args.include_hidden,
        follow_symlinks=args.follow_symlinks,
        skip_mount_points=args.skip_mount_points,
    )

    if not files:
        print("No files found to scan.")
        return 0

    print(f"Scanning {len(files)} files using engines: {args.engines}")
    print(f"Commit mode: {args.apply}")

    if args.apply and args.confirm:
        dry_results = run_fix_pass(files, args, apply=False)
        print_fix_summary(dry_results, verbose=args.verbose or args.debug)
        planned = [r for r in dry_results if r.action == "would-rename"]
        if not planned:
            print("No safe rename operations planned.")
            return 0
        answer = input("Proceed with renaming? (yes/no): ").strip().lower()
        if answer != "yes":
            print("Rename operation cancelled.")
            return 0
        results = run_fix_pass(files, args, apply=True)
    else:
        results = run_fix_pass(files, args, apply=args.apply)

    print_fix_summary(results, verbose=args.verbose or args.debug)
    return 1 if any(r.action == "error" for r in results) else 0


# ---------------------------------------------------------------------------
# Validate mode
# ---------------------------------------------------------------------------


def validate_one(path: Path, kind: str) -> tuple[Path, bool | None, str]:
    """Return (path, is_binary, description)."""
    binary = is_binary_file(path)
    if binary is None:
        return path, None, "access error"
    if kind == "binary":
        return path, binary, "binary" if binary else "text"
    return path, binary, "text" if not binary else "binary"


def cmd_validate(args: argparse.Namespace) -> int:
    """CLI handler for `validate binary|text`."""
    root = Path(args.path).expanduser()
    if not root.exists():
        eprint(f"Error: path {root} does not exist")
        return 2

    ext_set = BIN_EXT if args.kind == "binary" else TXT_EXT
    files = list(
        iter_files(
            root,
            recursive=True,
            skip_hidden=True,
            follow_symlinks=False,
            skip_mount_points=args.skip_mount_points,
        )
    )
    files = [
        p for p in files if current_ext(p) in ext_set or p.suffix.lower() in ext_set
    ]

    if not files:
        print("No files found with target extensions.")
        return 0

    print(
        f"Validating {len(files)} files as {args.kind} using {args.workers} workers..."
    )

    mismatches: list[tuple[Path, str]] = []
    errors = 0

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, args.workers)
    ) as pool:
        futures = [pool.submit(validate_one, path, args.kind) for path in files]
        for future in concurrent.futures.as_completed(futures):
            path, binary, desc = future.result()
            if binary is None:
                errors += 1
                continue
            expected_binary = args.kind == "binary"
            if binary != expected_binary:
                mismatches.append((path, desc))

    print()
    print("=" * 40)
    print(f"{args.kind.upper()} EXTENSION VALIDATION REPORT")
    print("-" * 40)
    print(f"  Total files found:    {len(files)}")
    print(f"  Mismatches:           {len(mismatches)}")
    print(f"  Access errors:        {errors}")

    if mismatches:
        print(f"\nMISMATCHES FOUND: {len(mismatches)}")
        for path, desc in mismatches[:20]:
            print(f"  {path}  ({desc})")
        if len(mismatches) > 20:
            print(f"  ... and {len(mismatches) - 20} more")
    else:
        print("\nNo mismatches found.")

    print("=" * 40)
    return 1 if mismatches else 0


# ---------------------------------------------------------------------------
# Extract-python mode (fpy.py)
# ---------------------------------------------------------------------------

PY_KEYWORDS = {"def", "class", "import", "from", "lambda", "yield", "async", "await"}


def looks_like_python_line(line: str) -> bool:
    """Return True if a line looks Python-like (from fpy.py)."""
    if any(keyword in line for keyword in PY_KEYWORDS):
        return True
    if re.search(r":\s*$", line):
        return True
    if re.match(r"\s{4}", line):
        return True
    return False


def is_valid_python_token_stream(text: str) -> bool:
    """Check tokenization validity."""
    try:
        tokenize.generate_tokens(StringIO(text).readline)
        return True
    except tokenize.TokenError:
        return False


def is_python_construct(line: str) -> bool:
    """Regex check for common Python constructs."""
    if re.match(r"\s*(def|class|if|elif|else|for|while|try|except|with)\b.*:", line):
        return True
    if re.match(r"\s*@[A-Za-z_]\w*", line):
        return True
    return bool(re.match(r"\s*import\b|\s*from\b", line))


def cmd_extract_python(args: argparse.Namespace) -> int:
    """CLI handler for `extract-python`."""
    source = Path(args.file)
    output = Path(args.output)

    try:
        text = source.read_text(encoding="utf-8")
    except FileNotFoundError:
        eprint(f"Error: File '{source}' not found.")
        return 1
    except Exception as exc:
        eprint(f"An error occurred: {exc}")
        return 1

    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    for line in lines:
        if is_python_construct(line) or looks_like_python_line(line):
            kept.append(line)
        elif is_valid_python_token_stream(line):
            kept.append(line)

    try:
        output.write_text("".join(kept), encoding="utf-8")
    except Exception as exc:
        eprint(f"Could not write {output}: {exc}")
        return 1

    print(f"Wrote {len(kept)} lines to {output}")
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the merged CLI parser."""
    parser = argparse.ArgumentParser(
        prog="filefixer.py",
        description="Detect/fix file-extension mismatches, validate binary/text extensions, or extract Python-like lines.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")

    sub = parser.add_subparsers(dest="command")

    # fix
    fix = sub.add_parser("fix", help="Detect and optionally fix extension mismatches.")
    fix.add_argument(
        "paths",
        nargs="*",
        help="Files/directories to scan. Default: current directory.",
    )
    fix.add_argument(
        "--scan-cwd",
        action="store_true",
        help="Ignore paths and scan CWD (fix_ext.py behavior).",
    )
    fix.add_argument(
        "--apply",
        "--commit",
        "-a",
        action="store_true",
        dest="apply",
        help="Actually rename files.",
    )
    fix.add_argument(
        "--confirm",
        action="store_true",
        help="Ask before live renames (fixext3.py behavior).",
    )
    fix.add_argument(
        "--engines",
        default="auto",
        help="Comma list: auto, shebang,puremagic,magic,filetype,file-mime,file-b,signature,mimetypes,text",
    )
    fix.add_argument(
        "--workers",
        "-j",
        type=int,
        default=max(1, (os.cpu_count() or 2) - 1),
        help="Worker threads.",
    )
    fix.add_argument(
        "--no-recursive", action="store_true", help="Do not recurse into directories."
    )
    fix.add_argument(
        "--include-hidden", action="store_true", help="Do not skip hidden files/dirs."
    )
    fix.add_argument(
        "--follow-symlinks", action="store_true", help="Follow symlinks while walking."
    )
    fix.add_argument(
        "--skip-mount-points",
        action="store_true",
        help="Do not cross filesystem boundaries.",
    )
    fix.add_argument(
        "--collision",
        choices=("suffix", "parenthesized", "skip", "overwrite"),
        default="suffix",
        help="Collision policy.",
    )
    fix.add_argument(
        "--protect-ext",
        default=",".join(sorted(DEFAULT_PROTECT_EXT)),
        help="Comma list of protected extensions.",
    )
    fix.add_argument(
        "--no-protect", action="store_true", help="Disable protected extensions."
    )
    fix.add_argument(
        "--force-protected",
        action="store_true",
        help="Allow renaming protected extensions.",
    )
    fix.add_argument(
        "--ignore-ext",
        default=",".join(sorted(DEFAULT_IGNORE_EXT)),
        help="Comma list of extensions to ignore.",
    )
    fix.add_argument(
        "--skip-text-mismatches",
        action="store_true",
        help="Skip .txt-to-.txt style mismatches.",
    )
    fix.add_argument("--verbose", "-v", action="store_true", help="Verbose output.")

    # validate
    val = sub.add_parser("validate", help="Validate binary or text extensions.")
    val.add_argument(
        "kind", choices=("binary", "text"), help="Which extension set to validate."
    )
    val.add_argument(
        "path", nargs="?", default="/data/data/com.termux", help="Root path to scan."
    )
    val.add_argument(
        "--workers",
        "-j",
        type=int,
        default=max(1, (os.cpu_count() or 2) - 1),
        help="Worker threads.",
    )
    val.add_argument(
        "--skip-mount-points",
        action="store_true",
        default=True,
        help="Do not cross filesystem boundaries.",
    )
    val.add_argument("--verbose", "-v", action="store_true", help="Verbose output.")

    # extract-python
    ext = sub.add_parser(
        "extract-python", help="Extract Python-like lines from a file."
    )
    ext.add_argument("file", help="Input file.")
    ext.add_argument(
        "-o", "--output", default="out.py", help="Output file. Default: out.py"
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "debug", False) else logging.WARNING,
        format="%(levelname)s | %(message)s",
    )

    if args.command == "fix":
        return cmd_fix(args)
    if args.command == "validate":
        return cmd_validate(args)
    if args.command == "extract-python":
        return cmd_extract_python(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
