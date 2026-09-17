#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import contextlib
import lzma
import shutil
import tarfile
import time
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

XZ_PRESET = 9
DEFAULT_WORKERS = 8


def dir_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def make_archive_path(subdir: Path) -> Path:
    return subdir.parent / f"{subdir.name}.tar.xz"


def compress_subdir(subdir: Path) -> dict:
    archive_path = make_archive_path(subdir)
    start_monotonic = time.monotonic()
    start_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    original_size = 0
    try:
        if not subdir.is_dir():
            raise FileNotFoundError(f"Source directory does not exist: {subdir}")
        if archive_path.exists():
            raise FileExistsError(
                f"Archive already exists; refusing to overwrite: {archive_path.name}"
            )
        original_size = dir_size(subdir)
        with (
            lzma.open(
                archive_path,
                mode="wb",
                preset=XZ_PRESET,
                check=lzma.CHECK_CRC64,
            ) as compressed_file,
            tarfile.open(
                fileobj=compressed_file,
                mode="w",
                dereference=False,
            ) as tar,
        ):
            tar.add(
                subdir,
                arcname=subdir.name,
                recursive=True,
            )
        with tarfile.open(archive_path, mode="r:xz") as tar:
            for member in tar:
                if member.isfile():
                    extracted = tar.extractfile(member)
                    if extracted is not None:
                        while extracted.read(1024 * 1024):
                            pass
        compressed_size = archive_path.stat().st_size
        if compressed_size <= 0:
            raise OSError("Created archive is empty")
        shutil.rmtree(subdir)
        end_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elapsed = time.monotonic() - start_monotonic
        ratio = compressed_size / original_size if original_size > 0 else 0.0
        return {
            "subdir": subdir.name,
            "success": True,
            "message": f"OK   {subdir.name}",
            "start": start_dt,
            "end": end_dt,
            "elapsed": elapsed,
            "original_size": original_size,
            "compressed_size": compressed_size,
            "ratio": ratio,
        }
    except Exception as exc:
        end_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elapsed = time.monotonic() - start_monotonic
        if archive_path.exists():
            with contextlib.suppress(OSError):
                archive_path.unlink()
        return {
            "subdir": subdir.name,
            "success": False,
            "message": f"FAIL {subdir.name}: {exc}",
            "start": start_dt,
            "end": end_dt,
            "elapsed": elapsed,
            "original_size": original_size,
            "compressed_size": 0,
            "ratio": 0.0,
        }


def fmt_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1024 or unit == "PB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def print_report(result: dict) -> None:
    status = "✅" if result["success"] else "❌"
    elapsed = f"{result['elapsed']:.1f}s"
    if result["success"]:
        ratio_percent = result["ratio"] * 40
        print(
            f"{status} {result['message']:<35} "
            f"start={result['start']}  "
            f"end={result['end']}  "
            f"took={elapsed:<7} "
            f"{fmt_size(result['original_size'])} -> "
            f"{fmt_size(result['compressed_size'])} "
            f"({ratio_percent:.1f}% of original)",
            flush=True,
        )
    else:
        print(
            f"{status} {result['message']:<35} "
            f"start={result['start']}  "
            f"end={result['end']}  "
            f"took={elapsed}",
            flush=True,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compress top-level subdirectories into .tar.xz archives."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Directory containing the subdirectories. Defaults to the current directory.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Number of worker processes. Defaults to {DEFAULT_WORKERS}.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.directory.expanduser().resolve()
    if not root.is_dir():
        print(f"Error: not a directory: {root}")
        return 1
    if args.workers < 1:
        print("Error: --workers must be at least 1")
        return 1
    subdirs = sorted(
        (
            item
            for item in root.iterdir()
            if item.is_dir() and not item.is_symlink() and not item.name.startswith(".")
        ),
        key=lambda path: path.name.lower(),
    )
    if not subdirs:
        print(f"No non-hidden top-level subdirectories found in: {root}")
        return 0
    worker_count = min(args.workers, len(subdirs))
    print(f"Directory: {root}")
    print(f"Subdirectories: {len(subdirs)}")
    print(f"Workers: {worker_count}")
    print(f"xz preset: {XZ_PRESET}")
    print()
    successful = 0
    failed = 0
    with Pool(processes=worker_count) as pool:
        for result in pool.imap_unordered(compress_subdir, subdirs):
            print_report(result)
            if result["success"]:
                successful += 1
            else:
                failed += 1
    print()
    print("Finished")
    print(f"Successful: {successful}")
    print(f"Failed:     {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
