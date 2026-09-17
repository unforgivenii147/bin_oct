#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import multiprocessing as mp
import shutil
import sys
from pathlib import Path

from loguru import logger


def clean_records():
    for dist_info in Path(".").glob("*.dist-info"):
        record_file = dist_info / "RECORD"
        if record_file.exists():
            lines = record_file.read_text().splitlines()
            filtered = []
            for line in lines:
                if line.strip():
                    parts = line.split(",")
                    if parts[0].endswith(".pyc"):
                        continue
                filtered.append(line)
            record_file.write_text("\n".join(filtered) + ("\n" if filtered else ""))


def copy_file(path_str, base_dir, dest_dir):
    try:
        src = Path(path_str)
        if not src.is_absolute():
            src = base_dir / src
        if src.exists() and src.is_file():
            rel = src.relative_to(base_dir)
            dst = dest_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    except Exception as e:
        logger.error(f"Error copying {path_str}: {e}")


def main():
    base_dir = Path.cwd()
    dest_dir = Path("~/tmp/packages").expanduser().resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    clean_records()
    files_to_copy = []
    for pkg in sys.argv[1:]:
        pkg_name = pkg.replace("-", "_")
        matched = set(base_dir.glob(f"{pkg_name}-*.dist-info")) | set(
            base_dir.glob(f"{pkg}-*.dist-info")
        )
        for dist_info in matched:
            record_file = dist_info / "RECORD"
            if record_file.exists():
                for line in record_file.read_text().splitlines():
                    if line.strip():
                        path = line.split(",")[0]
                        if path and not path.endswith(".pyc"):
                            files_to_copy.append(path)
    pool = mp.Pool(4)
    results = []
    for f in files_to_copy:
        res = pool.apply_async(copy_file, (f, base_dir, dest_dir))
        results.append(res)
    for res in results:
        try:
            res.get()
        except Exception as e:
            logger.error(f"Worker exception: {e}")
    pool.close()
    pool.join()


if __name__ == "__main__":
    main()
