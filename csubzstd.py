#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import tarfile
import time
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

import zstandard as zstd

ZSTD_LEVEL = 9
WORKERS = 8


def dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def compress_subdir(subdir: Path) -> dict:
    archive_path = subdir.with_suffix(subdir.suffix + ".tar.zst")
    start_time = time.monotonic()
    start_dt = datetime.now().strftime("%H:%M:%S")
    try:
        original_size = dir_size(subdir)
        cctx = zstd.ZstdCompressor(level=ZSTD_LEVEL)
        with open(archive_path, "wb") as f, cctx.stream_writer(f) as compressor:
            with tarfile.open(fileobj=compressor, mode="w") as tar:
                tar.add(subdir, arcname=subdir.name)
        end_time = time.monotonic()
        end_dt = datetime.now().strftime("%H:%M:%S")
        elapsed = end_time - start_time
        if not archive_path.is_file() or archive_path.stat().st_size == 0:
            return {
                "subdir": subdir.name,
                "success": False,
                "message": f"Archive {archive_path.name} is missing or empty",
                "start": start_dt,
                "end": end_dt,
                "elapsed": elapsed,
                "original_size": original_size,
                "compressed_size": 0,
                "ratio": 0.0,
            }
        compressed_size = archive_path.stat().st_size
        ratio = compressed_size / original_size if original_size > 0 else 0.0
        shutil.rmtree(subdir)
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
        end_time = time.monotonic()
        end_dt = datetime.now().strftime("%H:%M:%S")
        elapsed = end_time - start_time
        if archive_path.exists():
            archive_path.unlink()
        return {
            "subdir": subdir.name,
            "success": False,
            "message": f"FAIL {subdir.name}: {exc}",
            "start": start_dt,
            "end": end_dt,
            "elapsed": elapsed,
            "original_size": 0,
            "compressed_size": 0,
            "ratio": 0.0,
        }


def fmt_size(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


def print_report(r: dict) -> None:
    status = "✅" if r["success"] else "❌"
    elapsed_s = f"{r['elapsed']:.1f}s"
    if r["success"]:
        ratio_pct = r["ratio"] * 40
        print(
            f"{status} {r['message']:<40} "
            f"start={r['start']}  end={r['end']}  "
            f"took={elapsed_s:<6} "
            f"{fmt_size(r['original_size'])} -> {fmt_size(r['compressed_size'])} "
            f"({ratio_pct:.1f}% of original)"
        )
    else:
        print(
            f"{status} {r['message']:<40} "
            f"start={r['start']}  end={r['end']}  took={elapsed_s}"
        )


def main() -> None:
    cwd = Path.cwd()
    subdirs = sorted(
        [entry for entry in cwd.iterdir() if entry.is_dir()],
        key=lambda p: p.name.lower(),
    )
    if not subdirs:
        print("No top-level subdirectories found in", cwd)
        return
    print(f"Found {len(subdirs)} subdirectories to compress in {cwd}")
    print(f"Using {WORKERS} workers, zstd level {ZSTD_LEVEL}\n")
    results = []
    with Pool(processes=WORKERS) as pool:
        async_results = [
            pool.apply_async(compress_subdir, (subdir,)) for subdir in subdirs
        ]
        for async_result in async_results:
            r = async_result.get()
            print_report(r)
            results.append(r)
    ok = sum(1 for r in results if r["success"])
    fail = len(results) - ok
    total_orig = sum(r["original_size"] for r in results if r["success"])
    total_comp = sum(r["compressed_size"] for r in results if r["success"])
    total_time = sum(r["elapsed"] for r in results)
    print(f"\n{'=' * 40}")
    print(f"Done: {ok} succeeded, {fail} failed")
    if ok:
        print(
            f"Total: {fmt_size(total_orig)} -> {fmt_size(total_comp)} "
            f"({total_comp / total_orig * 40:.1f}% of original)"
        )
    print(f"Total wall time: {total_time:.1f}s")


if __name__ == "__main__":
    main()
