#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import stat
import sys
import time
from multiprocessing import Pool, cpu_count
from pathlib import Path

from dh import is_binary

DIR_PERM = 0o755
FILE_PERM = 0o664
EXEC_PERM = 0o755
SKIP_NAMES = {".git", "__pycache__", ".idea", "node_modules", ".venv", "venv"}
EXECUTABLE_DIRS = {"bin", "sbin", ".bin", "libexec", "scripts", "tools"}


def is_executable(mode: int) -> bool:
    return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def has_shebang(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            first_line = f.readline()
        return first_line.startswith(b"#!")
    except OSError:
        return False


def is_symlink(path: Path) -> bool:
    try:
        return path.is_symlink()
    except OSError:
        return False


def should_skip_path(path: Path) -> bool:
    return any(part in SKIP_NAMES for part in path.parts)


def is_in_executable_dir(path: Path) -> bool:
    return any(part in EXECUTABLE_DIRS for part in path.parts)


def can_write(path: Path) -> bool:
    try:
        parent = path.parent
        return parent.exists() and os.access(str(parent), os.W_OK)
    except (OSError, PermissionError):
        return False


def get_target_permission(path: Path, current_mode: int) -> tuple[int | None, str]:
    if is_symlink(path):
        return (None, "symbolic link")
    if path.is_dir():
        return (DIR_PERM, "directory")
    if is_executable(current_mode):
        if is_binary(path) or has_shebang(path):
            return (None, "executable binary/script (preserved)")
        return (FILE_PERM, "executable (normalizing to 664)")
    if is_in_executable_dir(path):
        return (EXEC_PERM, "file in executable directory")
    return (FILE_PERM, "regular file")


def process_path(path: Path) -> dict:
    result = {
        "dirs_changed": 0,
        "files_changed": 0,
        "files_made_exec": 0,
        "skipped": 0,
        "errors": 0,
        "permission_errors": 0,
        "other_errors": 0,
        "messages": [],
    }
    try:
        if should_skip_path(path):
            result["skipped"] += 1
            return result
        try:
            current_mode = stat.S_IMODE(path.stat().st_mode)
        except FileNotFoundError:
            return result
        except PermissionError:
            result["permission_errors"] += 1
            result["errors"] += 1
            return result
        target_perm, reason = get_target_permission(path, current_mode)
        if target_perm is None:
            result["skipped"] += 1
            return result
        if current_mode == target_perm:
            return result
        if not can_write(path):
            result["permission_errors"] += 1
            result["errors"] += 1
            return result
        try:
            path.chmod(target_perm)
        except PermissionError:
            result["permission_errors"] += 1
            result["errors"] += 1
            return result
        except OSError:
            result["other_errors"] += 1
            result["errors"] += 1
            return result
        if path.is_dir():
            result["dirs_changed"] += 1
            result["messages"].append(
                f"[DIR]  {str(path)[:60]} {oct(current_mode)} -> {oct(target_perm)}"
            )
        elif is_in_executable_dir(path) and (not is_executable(current_mode)):
            result["files_made_exec"] += 1
            result["messages"].append(
                f"[EXEC] {str(path)[:60]} {oct(current_mode)} -> {oct(target_perm)} ({reason})"
            )
        else:
            result["files_changed"] += 1
            result["messages"].append(
                f"[FILE] {str(path)[:60]} {oct(current_mode)} -> {oct(target_perm)}"
            )
    except Exception as e:
        result["other_errors"] += 1
        result["errors"] += 1
        result["messages"].append(f"[ERR]  {str(path)[:60]}: {type(e).__name__}: {e}")
    return result


def collect_paths(cwd: str) -> list[Path]:
    root = Path(cwd).resolve()
    if not root.exists():
        print(f"❌ Error: Path does not exist: {cwd}", file=sys.stderr)
        sys.exit(1)
    paths: list[Path] = []
    try:
        for current_dir, dirnames, filenames in os.walk(
            str(root), topdown=True, followlinks=False
        ):
            dirnames[:] = [d for d in dirnames if d not in SKIP_NAMES]
            cd = Path(current_dir)
            paths.append(cd)
            for name in filenames:
                paths.append(cd / name)
    except PermissionError as e:
        print(f"⚠️  Warning: Permission denied during traversal: {e}", file=sys.stderr)
    return paths


def merge_results(all_results: list[dict]) -> dict:
    merged = {
        "dirs_changed": 0,
        "files_changed": 0,
        "files_made_exec": 0,
        "skipped": 0,
        "errors": 0,
        "permission_errors": 0,
        "other_errors": 0,
        "messages": [],
    }
    for result in all_results:
        merged["dirs_changed"] += result["dirs_changed"]
        merged["files_changed"] += result["files_changed"]
        merged["files_made_exec"] += result["files_made_exec"]
        merged["skipped"] += result["skipped"]
        merged["errors"] += result["errors"]
        merged["permission_errors"] += result.get("permission_errors", 0)
        merged["other_errors"] += result.get("other_errors", 0)
        merged["messages"].extend(result["messages"])
    return merged


def print_summary(results: dict, total_items: int, elapsed_time: float) -> None:
    print("\n" + "=" * 40)
    print("📊 PERMISSION NORMALIZATION SUMMARY")
    print("-" * 40)
    print(f"⏱️  Time elapsed:          {elapsed_time:.2f} seconds")
    print(f"📁 Total items processed: {total_items}")
    print(f"⏭️  Skipped:              {results['skipped']}")
    print("-" * 40)
    print(f"✓  Directories changed:   {results['dirs_changed']}")
    print(f"✓  Files normalized:      {results['files_changed']}")
    print(f"✓  Files made executable: {results['files_made_exec']}")
    print(f"❌ Total errors:          {results['errors']}")
    if results.get("permission_errors", 0) > 0:
        print(f"   └─ Permission errors: {results['permission_errors']}")
    if results.get("other_errors", 0) > 0:
        print(f"   └─ Other errors:       {results['other_errors']}")
    print("-" * 40)
    if results.get("permission_errors", 0) > 0:
        print("\n💡 Tip: Permission errors can be fixed by:")
        print("   - Running with appropriate privileges (sudo/root)")
        print("   - Changing ownership of files")
        print("   - Running chmod on problematic directories first")


def print_details(results: dict, verbose: bool = False) -> None:
    if not verbose or not results["messages"]:
        return
    print("\n📝 DETAILED CHANGES:")
    print("-" * 40)
    dir_msgs = [m for m in results["messages"] if m.startswith("[DIR]")]
    exec_msgs = [m for m in results["messages"] if m.startswith("[EXEC]")]
    file_msgs = [m for m in results["messages"] if m.startswith("[FILE]")]
    err_msgs = [m for m in results["messages"] if m.startswith("[ERR]")]
    for msgs, label in [
        (dir_msgs, "Directory changes"),
        (exec_msgs, "Files made executable"),
        (file_msgs, "Files normalized"),
    ]:
        if msgs:
            print(f"\n{label}:")
            for msg in msgs[:50]:
                print(f"  {msg}")
            if len(msgs) > 50:
                print(f"  ... and {len(msgs) - 50} more")
    if err_msgs:
        print(f"\n❌ Errors ({len(err_msgs)}):")
        for msg in err_msgs[:20]:
            print(f"  {msg}")
        if len(err_msgs) > 20:
            print(f"  ... and {len(err_msgs) - 20} more")


def normalize_permissions(cwd: str = ".", verbose: bool = False) -> None:
    start_time = time.time()
    print(f"🔍 Scanning: {Path(cwd).resolve()}")
    all_paths = collect_paths(cwd)
    total = len(all_paths)
    if total == 0:
        print("⚠️  No files found to process.")
        return
    workers = min(cpu_count(), 4)
    print(f"📦 Found {total} items to process")
    print(f"⚙️  Using {workers} worker processes")
    print("🚀 Processing...\n")
    try:
        with Pool(processes=workers) as pool:
            chunksize = max(1000, total // (workers * 10))
            results_list = pool.imap_unordered(
                process_path, all_paths, chunksize=chunksize
            )
            all_results: list[dict] = []
            processed = 0
            for result in results_list:
                all_results.append(result)
                processed += 1
                if processed % 500 == 0 or processed == total:
                    print(
                        f"  Progress: {processed:,}/{total:,} ({100 * processed / total:.1f}%)"
                    )
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user!")
        pool.terminate()
        pool.join()
        sys.exit(1)
    final_results = merge_results(all_results)
    elapsed = time.time() - start_time
    print_summary(final_results, total, elapsed)
    print_details(final_results, verbose=verbose)
    print("\n✅ Done!")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Normalize file and directory permissions.",
        epilog="Example: python3 normalize_perms.py . -v",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to start normalization (default: current directory)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Print detailed changes"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress progress output"
    )
    args = parser.parse_args()
    try:
        normalize_permissions(args.path, verbose=args.verbose)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted!")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
