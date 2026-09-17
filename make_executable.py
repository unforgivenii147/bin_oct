#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import concurrent.futures
import os
import stat
from pathlib import Path

TEXT_SUFFIXES = {".py", ".sh", ".bash", ".pl", ".rb", ".pyw", ".txt"}


def check_and_make_executable(path: Path) -> dict:
    result = {
        "path": path,
        "is_shebang": False,
        "permission_changed": False,
        "error": None,
    }
    try:
        if not path.is_file():
            return result
        if path.suffix and path.suffix.lower() not in TEXT_SUFFIXES:
            return result
        with path.open("rb") as f:
            first_two_bytes = f.read(2)
        if first_two_bytes == b"#!":
            result["is_shebang"] = True
            if os.name == "posix":
                current_mode = path.stat().st_mode
                if not (current_mode & stat.S_IXUSR):
                    new_mode = current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                    path.chmod(new_mode)
                    result["permission_changed"] = True
    except Exception as e:
        result["error"] = f"Failed to process: {e}"
    return result


def main():
    current_dir = Path(".")
    print("🔍 Gathering directory contents recursively...")
    all_files = list(current_dir.rglob("*"))
    script_path = Path(__file__).resolve()
    target_files = [f for f in all_files if f.resolve() != script_path]
    if not target_files:
        print("ℹ️ No files discovered in the target workspace.")
        return
    cpu_cores = os.cpu_count() or 1
    print(
        f"⚡ Processing {len(target_files)} files concurrently across {cpu_cores} threads..."
    )
    print("-" * 40)
    total_shebangs = 0
    total_updated = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=cpu_cores) as executor:
        futures = {
            executor.submit(check_and_make_executable, f): f for f in target_files
        }
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res["error"]:
                print(f"❌ [ERROR] {res['path']}: {res['error']}")
                continue
            if res["is_shebang"]:
                total_shebangs += 1
                if res["permission_changed"]:
                    total_updated += 1
                    print(f"🚀 [MADE EXECUTABLE] {res['path']}")
                else:
                    print(f"✅ [ALREADY EXECUTABLE] {res['path']}")
    print("-" * 40)
    print("📊 Summary:")
    print(f"   Total shebang files found: {total_shebangs}")
    print(f"   Files updated with +x bit: {total_updated}")
    if os.name != "posix":
        print("\n⚠️ Note: You are running on a non-POSIX system (e.g. Windows).")
        print(
            "   Shebang files were detected but executable bits cannot be applied here."
        )


if __name__ == "__main__":
    raise SystemExit(main())
