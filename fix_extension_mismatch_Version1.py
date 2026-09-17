#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import shutil
import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path

READ_BYTES = 8192
SIGNATURES = [
    (lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"), ".png", "PNG image"),
    (lambda b: b.startswith(b"\xff\xd8\xff"), ".jpg", "JPEG image"),
    (lambda b: b.startswith((b"GIF87a", b"GIF89a")), ".gif", "GIF image"),
    (lambda b: b.startswith(b"BM"), ".bmp", "BMP image"),
    (
        lambda b: b.startswith((b"II*\x00", b"I\x00*\x00", b"MM\x00*")),
        ".tif",
        "TIFF image",
    ),
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
            b.startswith(b"ID3")
            or (len(b) >= 2 and (b[0] == 255 and b[1] & 224 == 224))
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
        "JSON-ish text (heuristic)",
    ),
    (lambda b: b.startswith(b"\x7fELF"), ".elf", "ELF binary"),
    (lambda b: b.startswith(b"MZ"), ".exe", "PE/EXE binary"),
]
PREFERRED_EXT = {".jpeg": ".jpg", ".tiff": ".tif", ".htm": ".html"}
SKIP_EXTS = {".py", ".pyc", ".pyo", ".so", ".dll"}


def detect_by_signature(path: Path, nbytes: int = READ_BYTES) -> tuple[str, str] | None:
    try:
        with path.open("rb") as f:
            head = f.read(nbytes)
    except PermissionError:
        return None
    except OSError:
        return None
    for check, ext, desc in SIGNATURES:
        try:
            if check(head):
                canonical = PREFERRED_EXT.get(ext, ext)
                return canonical, desc
        except Exception:
            continue
    try:
        import zipfile

        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path, "r") as z:
                for nm in z.namelist():
                    if nm.endswith(".dist-info/"):
                        return ".whl", "Python wheel (zip)"
                    if nm.endswith(".egg-info/"):
                        return ".zip", "Python egg archive"
            return ".zip", "ZIP archive"
    except Exception:
        pass
    try:
        import tarfile

        if tarfile.is_tarfile(path):
            return ".tar", "TAR archive"
    except Exception:
        pass
    try:
        with path.open("rb") as f:
            sample = f.read(1024)
        if not sample:
            return None
        printable = sum(1 for c in sample if 32 <= c <= 126 or c in (9, 10, 13))
        if printable / max(1, len(sample)) > 0.9:
            return ".txt", "Plain text (heuristic)"
    except Exception:
        pass
    return None


def safe_rename(src: Path, dst: Path) -> tuple[bool, str | None]:
    if src.samefile(dst) if dst.exists() and src.exists() else False:
        return False, "source and destination are identical"
    if not dst.exists():
        try:
            src.rename(dst)
            return True, str(dst)
        except OSError:
            try:
                shutil.move(str(src), str(dst))
                return True, str(dst)
            except Exception as e:
                return False, f"rename/move failed: {e}"
    base = dst.stem
    suff = dst.suffix
    parent = dst.parent
    for i in range(1, 1000):
        candidate = parent / f"{base}_{i}{suff}"
        if not candidate.exists():
            try:
                src.rename(candidate)
                return True, str(candidate)
            except OSError:
                try:
                    shutil.move(str(src), str(candidate))
                    return True, str(candidate)
                except Exception as e:
                    return False, f"rename/move failed for candidate: {e}"
    return False, "failed to find non-conflicting name"


def process_file(args) -> dict:
    path_str, commit, _verbose = args
    path = Path(path_str)
    result = {
        "path": str(path),
        "action": "skipped",
        "reason": None,
        "detected": None,
        "target": None,
    }
    if not path.is_file():
        result["reason"] = "not a file"
        return result
    try:
        detected = detect_by_signature(path)
    except Exception as e:
        result["reason"] = f"detection error: {e}"
        return result
    if not detected:
        result["reason"] = "unknown type"
        return result
    ext, desc = detected
    result["detected"] = {"ext": ext, "desc": desc}
    cur_ext = path.suffix.lower()
    cur_ext_norm = PREFERRED_EXT.get(cur_ext, cur_ext)
    if cur_ext_norm == ext:
        result["action"] = "ok"
        return result
    if cur_ext_norm in SKIP_EXTS:
        result["action"] = "skipped"
        result["reason"] = f"skipped extension {cur_ext_norm}"
        return result
    if path.suffix:
        target = path.with_name(path.stem + ext)
    else:
        target = path.with_name(path.name + ext)
    if target == path:
        result["action"] = "skipped"
        result["reason"] = "target equals source"
        return result
    if not commit:
        result["action"] = "would-rename"
        result["target"] = str(target)
        result["reason"] = f"{desc}"
        return result
    ok, info = safe_rename(path, target)
    if ok:
        result["action"] = "renamed"
        result["target"] = info
    else:
        result["action"] = "error"
        result["reason"] = info
    return result


def gather_files(
    root: Path, follow_symlinks: bool = False, skip_hidden: bool = True
) -> list[Path]:
    files: list[Path] = []
    for p in root.rglob("*"):
        try:
            if p.is_file():
                if skip_hidden and any(
                    part.startswith(".") for part in p.relative_to(root).parts
                ):
                    continue
                files.append(p)
        except Exception:
            continue
    return files


def print_summary(results: list[dict], verbose: bool = False) -> None:
    renamed = [r for r in results if r["action"] == "renamed"]
    would = [r for r in results if r["action"] == "would-rename"]
    skipped = [r for r in results if r["action"] in ("skipped", "ok")]
    errors = [r for r in results if r["action"] == "error"]
    print()
    print("Summary:")
    print(f"  files scanned: {len(results)}")
    print(f"  would-rename (dry-run): {len(would)}")
    print(f"  renamed: {len(renamed)}")
    print(f"  skipped/ok: {len(skipped)}")
    print(f"  errors: {len(errors)}")
    if verbose:
        if would:
            print("\nWould-rename examples:")
            for r in would[:10]:
                print(f"  {r['path']} -> {r.get('target')}  ({r.get('detected')})")
        if renamed:
            print("\nRenamed examples:")
            for r in renamed[:10]:
                print(f"  {r['path']} -> {r.get('target')}")
        if errors:
            print("\nErrors:")
            for r in errors[:10]:
                print(f"  {r['path']}: {r.get('reason')}")


def main():
    ap = argparse.ArgumentParser(
        prog="fix_extension_mismatch.py",
        description="Fix extension mismatches using file signatures",
    )
    ap.add_argument(
        "path", nargs="?", default=".", help="Root path to scan (default: .)"
    )
    ap.add_argument(
        "--workers",
        "-j",
        type=int,
        default=max(1, cpu_count() - 1),
        help="Number of worker processes (default: cpu_count()-1)",
    )
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Perform renames. Without this flag the script runs in dry-run mode.",
    )
    ap.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    ap.add_argument(
        "--follow-symlinks", action="store_true", help="Follow symlinks when scanning"
    )
    ap.add_argument(
        "--no-skip-hidden",
        action="store_true",
        help="Do not skip hidden files/directories (default: skip)",
    )
    args = ap.parse_args()
    root = Path(args.path).resolve()
    if not root.exists():
        print(f"Error: path {root} does not exist", file=sys.stderr)
        sys.exit(2)
    files = gather_files(
        root, follow_symlinks=args.follow_symlinks, skip_hidden=not args.no_skip_hidden
    )
    if not files:
        print("No files found to scan.")
        return
    print(
        f"Scanning {len(files)} files under {root} using {args.workers} workers. Commit mode: {args.commit}"
    )
    worker_args = [(str(p), args.commit, args.verbose) for p in files]
    results: list[dict] = []
    try:
        with Pool(processes=args.workers) as pool:
            for res in pool.imap_unordered(process_file, worker_args):
                results.append(res)
                if args.verbose:
                    p = res["path"]
                    act = res["action"]
                    if act in ("would-rename", "renamed"):
                        print(
                            f"{act}: {p} -> {res.get('target')} ({res.get('detected')})"
                        )
                    elif act == "ok":
                        print(f"ok: {p} (already matched)")
                    else:
                        print(f"{act}: {p} ({res.get('reason')})")
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        sys.exit(1)
    print_summary(results, verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
