#!/data/data/com.termux/files/home/.local/bin/python
"""
archive_report.py — Unified archive scanner and uncompressed-size reporter.

This single file merges three near-duplicate scripts into one CLI:

    * xreport.py   — full archive scan (integrity, extracted size, auto-extract, JSON)
    * xreport2.py  — byte-for-byte equivalent of xreport.py (renamed identifiers)
    * zreport.py   — focused report of *accurately measured* uncompressed sizes
                     plus a "do you have enough disk space?" warning

Equivalent invocations
----------------------
    python xreport.py  DIR [-a] [-t] [-v] [-j]
        ->  python archive_report.py scan DIR [-a] [-t] [-v] [-j]

    python xreport2.py DIR [-a] [-t] [-v] [-j]
        ->  python archive_report.py scan DIR [-a] [-t] [-v] [-j]

    python zreport.py  [PATH]
        ->  python archive_report.py sizes [PATH]

Usage examples
--------------
    # Quick scan of the current directory
    python archive_report.py

    # Full scan with per-file details and auto-extraction
    python archive_report.py scan ~/Downloads -v -a

    # Machine-readable output
    python archive_report.py scan . -j

    # Report *exact* uncompressed sizes and disk-space headroom
    python archive_report.py sizes ~/Downloads

Notes / compatibility quirks preserved from the originals
--------------------------------------------------------
* In the original `xreport*.py`, `-t/--test-integrity` actually toggles the
  banner and `-v/--verbose` toggles per-file output. We keep that behaviour
  so existing command lines keep working, but the --help text now explains it.
* `.tar.bz3` and `.tar.snappy` fall into the generic tar branch (they can't be
  opened by `tarfile`), so they are reported as FAIL with an estimated size —
  exactly like the originals.

Optional third-party packages (used when available):
    py7zr       — .7z support
    zstandard   — .zst support
    lz4.frame   — .lz4 support
    snappy      — .snappy support (estimate)
    brotli      — .br support (estimate)
"""

from __future__ import annotations

import argparse
import bz2
import gzip
import json
import lzma
import os
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# Optional third-party dependencies
# --------------------------------------------------------------------------- #
try:
    import py7zr  # type: ignore
except ImportError:
    py7zr = None

try:
    import zstandard as zstd  # type: ignore
except ImportError:
    zstd = None

try:
    import lz4.frame as lz4_frame  # type: ignore  # noqa: F401
except ImportError:
    lz4_frame = None

try:
    import snappy  # type: ignore  # noqa: F401
except ImportError:
    snappy = None

try:
    import brotli  # type: ignore  # noqa: F401
except ImportError:
    brotli = None


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def fsz(n: float) -> str:
    """Return a human-readable size string (e.g. ``1.50 MB``)."""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1024.0 or unit == "PB":
            return f"{int(n)} B" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} PB"


BANNER = """
    ___               __     _             _____
   / _ | ___________ / /_   (_)__  _____  / ___/______ ____  ___ ____
  / __ |/ __/ __/ -_) __/  / / _ \\/ ___/ / /__/ __/ _ `/ _ \\/ -_) __/
 /_/ |_/_/  \\__/\\__/\\__/  /_/\\___/_/     \\___/\\__/\\_,_/ .__/\\__/_/
                                                      /_/
  [ INTEGRITY VALIDATION & EXTRACTED SIZE SCANNER v1.4.2 ]
"""


# --------------------------------------------------------------------------- #
# Archive registry used by the `scan` command (25 extensions)
# --------------------------------------------------------------------------- #
ARCHIVE_TYPES: Dict[str, str] = {
    ".tar": "TAR Archive (.tar)",
    ".tar.gz": "GZip Tarball (.tar.gz)",
    ".tgz": "GZip Tarball (.tgz)",
    ".tar.xz": "XZ Tarball (.tar.xz)",
    ".txz": "XZ Tarball (.txz)",
    ".tar.bz2": "BZip2 Tarball (.tar.bz2)",
    ".tbz2": "BZip2 Tarball (.tbz2)",
    ".tar.lz4": "LZ4 Tarball (.tar.lz4)",
    ".tar.zst": "Zstandard Tarball (.tar.zst)",
    ".tzst": "Zstandard Tarball (.tzst)",
    ".tar.br": "Brotli Tarball (.tar.br)",
    ".tar.7z": "7-Zip Tarball (.tar.7z)",
    ".tar.bz3": "BZip3 Tarball (.tar.bz3)",
    ".tar.snappy": "Snappy Tarball (.tar.snappy)",
    ".zip": "ZIP Archive (.zip)",
    ".whl": "Python Wheel (.whl)",
    ".7z": "7-Zip Archive (.7z)",
    ".snappy": "Snappy Stream (.snappy)",
    ".zst": "Zstandard Stream (.zst)",
    ".gz": "GZip Stream (.gz)",
    ".bz3": "BZip3 Stream (.bz3)",
    ".bz2": "BZip2 Stream (.bz2)",
    ".xz": "XZ Compressed (.xz)",
    ".br": "Brotli Stream (.br)",
    ".lz4": "LZ4 Frame (.lz4)",
}

# Match longest extension first so ".tar.gz" wins over ".gz".
_SORTED_EXTS: Tuple[str, ...] = tuple(sorted(ARCHIVE_TYPES, key=len, reverse=True))


def detect_archive(path: Path) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(extension, description)`` if ``path`` looks like an archive."""
    name = path.name.lower()
    for ext in _SORTED_EXTS:
        if name.endswith(ext):
            return ext, ARCHIVE_TYPES[ext]
    return None, None


# --------------------------------------------------------------------------- #
# `scan` command — mirrors xreport.py / xreport2.py
# --------------------------------------------------------------------------- #
def _gzip_stream_size(path: Path) -> int:
    """Read the ISIZE footer of a gzip stream (mod 2**32), or estimate."""
    try:
        with open(path, "rb") as f:
            f.seek(-4, os.SEEK_END)
            return int.from_bytes(f.read(4), "little")
    except Exception:
        return int(path.stat().st_size * 2.8)


def _zstd_frame_size(path: Path) -> int:
    """Best-effort zstd uncompressed size, or estimate."""
    if zstd is not None:
        try:
            with open(path, "rb") as f:
                head = f.read(1024)
            params = (
                zstd.get_frame_parameters(head)
                if hasattr(zstd, "get_frame_parameters")
                else zstd.ZstdDecompressor().frame_parameters(head)
            )
            size = getattr(params, "content_size", 0) or getattr(
                params, "uncompressed_size", 0
            )
            if size and size > 0:
                return int(size)
        except Exception:
            pass
    return int(path.stat().st_size * 3.2)


def analyze_archive(path: Path) -> Dict[str, Any]:
    """
    Analyse one archive and return the same dict shape as the originals:

        {'path', 'filename', 'ext', 'archive_type', 'compressed_size',
         'extracted_size', 'file_count', 'ratio', 'integrity', 'error'}
    """
    ext, desc = detect_archive(path)
    size = path.stat().st_size
    extracted = 0
    count = 0
    integrity: Optional[bool] = None
    err = ""

    try:
        # ---- ZIP / wheel ----------------------------------------------------
        if ext in (".zip", ".whl"):
            with zipfile.ZipFile(path, "r") as zf:
                infos = zf.infolist()
                extracted = sum(i.file_size for i in infos)
                count = len(infos)
                integrity = zf.testzip() is None

        # ---- TAR family (incl. compressed tarballs) -------------------------
        elif ext and (
            ext.startswith(".tar") or ext in (".tgz", ".txz", ".tbz2", ".tzst")
        ):
            mode = "r:*"
            if ext in (".tar.gz", ".tgz"):
                mode = "r:gz"
            elif ext in (".tar.bz2", ".tbz2"):
                mode = "r:bz2"
            elif ext in (".tar.xz", ".txz"):
                mode = "r:xz"
            try:
                with tarfile.open(path, mode) as tf:
                    members = tf.getmembers()
                    extracted = sum(m.size for m in members)
                    count = len(members)
                    integrity = True
            except Exception as te:
                # Special-case .tar.zst / .tzst (tarfile can't open zstd).
                if zstd is not None and ext in (".tar.zst", ".tzst"):
                    dec = zstd.ZstdDecompressor()
                    with (
                        open(path, "rb") as f,
                        dec.stream_reader(f) as sr,
                        tarfile.open(fileobj=sr, mode="r|*") as tf,
                    ):
                        extracted = sum(m.size for m in tf)
                        count, integrity = 1, True
                else:
                    extracted = int(size * 3.5)
                    integrity, err = False, str(te)

        # ---- 7-Zip ----------------------------------------------------------
        elif ext == ".7z":
            if py7zr is not None:
                with py7zr.SevenZipFile(path, "r") as sz:
                    extracted = sz.archive_info().uncompressed
                    count = len(sz.getnames())
                    integrity = True
            else:
                extracted, integrity = int(size * 4.1), True

        # ---- Single-stream formats -----------------------------------------
        elif ext == ".gz":
            extracted, count, integrity = _gzip_stream_size(path), 1, True
        elif ext == ".zst":
            extracted, count, integrity = _zstd_frame_size(path), 1, True
        elif ext in (
            ".bz2",
            ".xz",
            ".lz4",
            ".br",
            ".snappy",
            ".bz3",
            ".tar.bz3",
            ".tar.snappy",
        ):
            ratios = {".bz2": 2.9, ".xz": 3.8, ".lz4": 2.4, ".br": 3.1}
            extracted = int(size * ratios.get(ext, 3.0))
            count, integrity = 1, True

        # ---- Fallback -------------------------------------------------------
        else:
            extracted, count, integrity = int(size * 2.5), 1, True

    except Exception as e:
        integrity, err, extracted = False, str(e), size

    return {
        "path": str(path),
        "filename": path.name,
        "ext": ext or "unknown",
        "archive_type": desc or "Unknown Archive",
        "compressed_size": size,
        "extracted_size": extracted,
        "file_count": count,
        "ratio": extracted / size if size > 0 else 1.0,
        "integrity": integrity,
        "error": err,
    }


def extract_archive(path: Path, dest_root: Path) -> Tuple[bool, str]:
    """Extract ``path`` under ``dest_root/<name>_extracted``."""
    ext, _ = detect_archive(path)
    dest = dest_root / f"{path.name}_extracted"
    dest.mkdir(parents=True, exist_ok=True)

    try:
        if ext in (".zip", ".whl"):
            with zipfile.ZipFile(path, "r") as zf:
                zf.extractall(dest)
            return True, str(dest)

        if ext and (
            ext.startswith(".tar") or ext in (".tgz", ".txz", ".tbz2", ".tzst")
        ):
            with tarfile.open(path, "r:*") as tf:
                try:
                    tf.extractall(dest, filter="data")  # py3.12+
                except TypeError:
                    tf.extractall(dest)
            return True, str(dest)

        if ext == ".7z" and py7zr is not None:
            with py7zr.SevenZipFile(path, "r") as sz:
                sz.extractall(path=dest)
            return True, str(dest)

        if ext == ".gz":
            out = dest / path.stem
            with gzip.open(path, "rb") as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            return True, str(dest)

        # Fallback: raw copy (same as the originals' "decompressed" placeholder).
        shutil.copyfile(path, dest / f"{path.name}.decompressed")
        return True, str(dest)

    except Exception as e:
        return False, str(e)


def cmd_scan(
    directory: str,
    auto_extract: bool,
    banner: bool,
    verbose: bool,
    as_json: bool,
) -> int:
    """Entry point of the ``scan`` subcommand (mirrors xreport*.py)."""
    root = Path(directory).resolve()

    if as_json:
        results = [
            analyze_archive(p)
            for p in root.rglob("*")
            if p.is_file() and detect_archive(p)[0]
        ]
        print(json.dumps(results, indent=2))
        return 0

    print(f"\x1b[38;5;39mScanning directory recursively:\x1b[0m {root}")
    if banner:
        print(f"\x1b[38;5;82m{BANNER}\x1b[0m")

    results: List[Dict[str, Any]] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if not detect_archive(p)[0]:
            continue

        info = analyze_archive(p)
        results.append(info)

        if verbose:
            status = (
                "\x1b[32m[PASS]\x1b[0m"
                if info["integrity"]
                else "\x1b[31m[FAIL]\x1b[0m"
            )
            print(
                f"->Found:{info['filename']}|Type:{info['archive_type']}"
                f"|Comp:{fsz(info['compressed_size'])}"
                f"->Ext:{fsz(info['extracted_size'])}|{status}"
            )

    # --- table header ---
    print("-" * 40)
    print(
        f"\x1b[1;37m{'FILENAME':<32} {'ARCHIVE TYPE':<26} "
        f"{'COMPRESSED':<12} {'EXTRACTED':<12} {'INTEGRITY':<10}\x1b[0m"
    )
    print("-" * 40)

    total_comp = sum(i["compressed_size"] for i in results)
    total_ext = sum(i["extracted_size"] for i in results)

    for info in results:
        if info["integrity"] is True:
            st = "\x1b[32mPASSED\x1b[0m"
        elif info["integrity"] is False:
            st = "\x1b[31mFAILED\x1b[0m"
        else:
            st = "\x1b[90mSKIP\x1b[0m"
        print(
            f"{info['filename'][:31]:<32} {info['archive_type'][:25]:<26} "
            f"{fsz(info['compressed_size']):<12} "
            f"{fsz(info['extracted_size']):<12} {st}"
        )

    print("=" * 40)
    print(f"\x1b[1;36mSUMMARY:\x1b[0m Found {len(results)} archive files.")
    print(f"Total Compressed Size : {fsz(total_comp)}")
    print(f"Total Extracted Size  : \x1b[1;32m{fsz(total_ext)}\x1b[0m")
    if total_comp > 0:
        print(
            f"Overall Expansion     : {total_ext / total_comp:.2f}x "
            f"({fsz(total_ext - total_comp)} saved)"
        )

    if auto_extract and results:
        dest_root = root / "extracted_archives"
        print(
            f"\n\x1b[38;5;214m[-a] Auto-extracting {len(results)} archives "
            f"into:\x1b[0m {dest_root}"
        )
        for info in results:
            ok, out = extract_archive(Path(info["path"]), dest_root)
            if ok:
                print(
                    f"  \x1b[32m[\u2713]\x1b[0m Extracted {info['filename']} -> {out}"
                )
            else:
                print(f"  \x1b[31m[\u2717]\x1b[0m Failed {info['filename']}: {out}")

    return 0


# --------------------------------------------------------------------------- #
# `sizes` command — mirrors zreport.py
# --------------------------------------------------------------------------- #
SKIP_DIRS = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)


def _count_stream(reader) -> int:
    """Read ``reader`` to EOF and return total bytes."""
    total = 0
    while True:
        chunk = reader.read(1 << 20)
        if not chunk:
            break
        total += len(chunk)
    return total


# Each handler: (path) -> (uncompressed_size | None, error | None)
_SizeHandler = Callable[[Path], Tuple[Optional[int], Optional[str]]]


def _h_tar(path: Path) -> Tuple[Optional[int], Optional[str]]:
    try:
        with tarfile.open(path, "r:*") as tf:
            return sum(m.size for m in tf.getmembers() if m.isfile()), None
    except Exception as e:
        return None, str(e)


def _h_zstd(path: Path) -> Tuple[Optional[int], Optional[str]]:
    if zstd is None:
        return None, "zstandard not installed"
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            dec = zstd.ZstdDecompressor()
            params = (
                zstd.get_frame_parameters(head)
                if hasattr(zstd, "get_frame_parameters")
                else dec.frame_parameters(head)
            )
            size = getattr(params, "content_size", 0) or getattr(
                params, "uncompressed_size", 0
            )
            if size:
                return int(size), None
            f.seek(0)
            return _count_stream(dec.stream_reader(f)), None
    except Exception as e:
        return None, str(e)


def _h_xz(path: Path) -> Tuple[Optional[int], Optional[str]]:
    try:
        with lzma.open(path, "rb") as f:
            return _count_stream(f), None
    except Exception as e:
        return None, str(e)


def _h_gzip(path: Path) -> Tuple[Optional[int], Optional[str]]:
    try:
        with gzip.open(path, "rb") as f:
            return _count_stream(f), None
    except Exception as e:
        return None, str(e)


def _h_bz2(path: Path) -> Tuple[Optional[int], Optional[str]]:
    try:
        with bz2.open(path, "rb") as f:
            return _count_stream(f), None
    except Exception as e:
        return None, str(e)


def _h_7z(path: Path) -> Tuple[Optional[int], Optional[str]]:
    if py7zr is None:
        return None, "py7zr not installed"
    try:
        with py7zr.SevenZipFile(path, "r") as z:
            return (
                sum(f.uncompressed for f in z.list() if f.uncompressed is not None),
                None,
            )
    except Exception as e:
        return None, str(e)


def _h_zip(path: Path) -> Tuple[Optional[int], Optional[str]]:
    try:
        with zipfile.ZipFile(path, "r") as z:
            return sum(i.file_size for i in z.infolist()), None
    except Exception as e:
        return None, str(e)


SIZE_HANDLERS: Dict[str, Tuple[str, _SizeHandler]] = {
    ".zst": ("zstd", _h_zstd),
    ".xz": ("xz", _h_xz),
    ".gz": ("gzip", _h_gzip),
    ".bz2": ("bzip2", _h_bz2),
    ".7z": ("7zip", _h_7z),
    ".zip": ("zip", _h_zip),
    ".whl": ("wheel", _h_zip),
    ".tar": ("tar", _h_tar),
}


def cmd_sizes(directory: str) -> int:
    """Entry point of the ``sizes`` subcommand (mirrors zreport.py)."""
    root = Path(directory).resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory")
        return 1

    print(f"Scanning {root}...\n")

    fmt = "{:<30} {:<10} {:>15} {:>15} {:>8}"
    print(fmt.format("File", "Format", "Compressed", "Uncompressed", "Ratio"))
    print("-" * 40)

    count = 0
    total_comp = 0
    total_uncomp = 0

    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue

        handler = next(
            (
                (name, fn)
                for ext, (name, fn) in SIZE_HANDLERS.items()
                if p.name.endswith(ext)
            ),
            None,
        )
        if handler is None:
            continue

        name, fn = handler
        size = p.stat().st_size
        uncomp, _err = fn(p)

        count += 1
        total_comp += size

        if uncomp is not None:
            total_uncomp += uncomp
            ratio = uncomp / size if size > 0 else 0.0
            ratio_s = f"{ratio:.2f}x"
            size_s = fsz(uncomp)
        else:
            ratio_s = "Error"
            size_s = "Error"

        display = p.name[:27] + "..." if len(p.name) > 30 else p.name
        print(fmt.format(display, name, fsz(size), size_s, ratio_s))

    print("-" * 40)
    print(f"Total files: {count}")
    print(f"Total compressed: {fsz(total_comp)}")
    print(f"Total uncompressed: {fsz(total_uncomp)}")

    try:
        _, _, free = shutil.disk_usage(root)
        print(f"Free disk space: {fsz(free)}")
        if total_uncomp > free:
            shortfall = total_uncomp - free
            print(
                f"\n\u26a0\ufe0f  WARNING: Not enough space to extract all files! "
                f"(Shortfall: {fsz(shortfall)})"
            )
    except OSError:
        pass

    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with ``scan`` and ``sizes``."""
    parser = argparse.ArgumentParser(
        prog="archive_report.py",
        description=(
            "Unified archive scanner and uncompressed-size reporter "
            "(merges xreport.py, xreport2.py, zreport.py)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  archive_report.py scan . -a -v\n"
            "  archive_report.py scan ~/Downloads -j\n"
            "  archive_report.py sizes ~/Downloads\n"
        ),
    )
    sub = parser.add_subparsers(dest="command")

    # ---- scan --------------------------------------------------------------
    sp_scan = sub.add_parser(
        "scan",
        help="Full archive scan with integrity check + auto-extract "
        "(≈ xreport.py / xreport2.py).",
    )
    sp_scan.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory).",
    )
    sp_scan.add_argument(
        "-a",
        "--auto-extract-all",
        action="store_true",
        help="Extract every discovered archive into <dir>/extracted_archives.",
    )
    # NOTE: name kept for backward compatibility with xreport*.py, where
    # --test-integrity actually toggles the banner.
    sp_scan.add_argument(
        "-t",
        "--test-integrity",
        action="store_true",
        help="Print the ASCII banner at the start of the scan "
        "(preserved from the original scripts).",
    )
    sp_scan.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print a detail line for every archive as it is analysed.",
    )
    sp_scan.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit the scan result as JSON and exit.",
    )
    sp_scan.set_defaults(
        func=lambda a: cmd_scan(
            a.directory, a.auto_extract_all, a.test_integrity, a.verbose, a.json
        )
    )

    # ---- sizes -------------------------------------------------------------
    sp_sizes = sub.add_parser(
        "sizes",
        help="Report *accurately measured* uncompressed sizes and disk-space "
        "headroom (≈ zreport.py).",
    )
    sp_sizes.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory).",
    )
    sp_sizes.set_defaults(func=lambda a: cmd_sizes(a.path))

    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    """Program entry point."""
    argv_list = list(sys.argv[1:] if argv is None else argv)

    # Default to `scan` when the user does not name a subcommand (so bare
    # `python archive_report.py DIR -a` keeps working like the originals).
    known = {"scan", "sizes", "-h", "--help"}
    if not argv_list or argv_list[0] not in known:
        argv_list = ["scan", *argv_list]

    parser = build_parser()
    args = parser.parse_args(argv_list)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
