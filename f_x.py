#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
import time
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path


def check_file_age(path):
    try:
        mod_time = path.stat().st_mtime
        current_time = time.time()
        age_minutes = (current_time - mod_time) / 60
        if age_minutes <= n_minutes:
            mod_datetime = datetime.fromtimestamp(mod_time)
            return str(path), mod_datetime
    except (OSError, PermissionError):
        pass
    return None


def main():
    global n_minutes
    if len(sys.argv) < 2:
        print("Usage: python script.py <minutes>")
        sys.exit(1)
    try:
        n_minutes = int(sys.argv[1])
    except ValueError:
        print(f"Error: '{sys.argv[1]}' is not a valid integer")
        sys.exit(1)
    if n_minutes < 0:
        print("Error: minutes must be a non-negative number")
        sys.exit(1)
    cwd = Path.cwd()
    all_files = [
        p
        for p in cwd.rglob("*")
        if p.is_file() and not p.is_symlink() and ".git" not in p.parts
    ]
    if not all_files:
        print("No files found in current directory")
        return
    print(
        f"Checking {len(all_files)} files for modifications in last {n_minutes} minute(s)..."
    )
    print()
    pool = Pool(8)
    results = pool.map(check_file_age, all_files)
    pool.close()
    pool.join()
    recent_files = [r for r in results if r is not None]
    recent_files.sort(key=lambda x: x[1], reverse=True)
    if recent_files:
        print(
            f"Found {len(recent_files)} file(s) modified in the last {n_minutes} minute(s):\n"
        )
        for path, mod_time in recent_files:
            print(
                f"{mod_time.strftime('%Y-%m-%d %H:%M:%S')} - {Path(path).relative_to(cwd)}"
            )
    else:
        print(f"No files modified in the last {n_minutes} minute(s)")


if __name__ == "__main__":
    raise SystemExit(main())
