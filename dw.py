#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import contextlib
import shutil
import sys
import time
from pathlib import Path


def tail_file(fname, n=10):
    try:
        with open(fname) as f:
            lines = f.readlines()
            return lines[-n:] if lines else []
    except OSError as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        return []


def get_all_files(folder):
    files = {}
    try:
        base = Path(folder)
        for p in base.rglob("*"):
            if p.is_file():
                with contextlib.suppress(OSError):
                    files[str(p)] = p.stat().st_mtime
    except OSError as e:
        print(f"Error scanning folder: {e}", file=sys.stderr)
    return files


def copy_file(src, dst_folder: Path | None) -> bool:
    try:
        if dst_folder:
            dst_folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst_folder)
        return True
    except OSError as e:
        print(f"Error copying file: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Recursively watch folder for file changes"
    )
    parser.add_argument("folder", help="Folder to watch")
    parser.add_argument(
        "-c", "--copy", action="store_true", help="Copy changed files to ~/tmp/tmp"
    )
    args = parser.parse_args()
    folder = Path(args.folder)
    copy_enabled = args.copy
    if not folder.is_dir():
        print(f"Error: Folder '{folder}' not found", file=sys.stderr)
        sys.exit(1)
    copy_dest = None
    if copy_enabled:
        copy_dest = Path.home() / "tmp" / "tmp"
        print(f"Copy mode enabled. Destination: {copy_dest}\n")
    file_mtimes = get_all_files(folder)
    print(f"Watching folder '{folder}' recursively...")
    print(f"Tracking {len(file_mtimes)} files\n")
    print("(Press Ctrl+C to exit)\n")
    try:
        while True:
            current_files = get_all_files(folder)
            for path_str, current_mtime in current_files.items():
                path = Path(path_str)
                last_mtime = file_mtimes.get(path_str)
                if last_mtime is None or current_mtime > last_mtime:
                    file_mtimes[path_str] = current_mtime
                    if last_mtime is not None:
                        try:
                            rel_path = path.relative_to(folder)
                        except ValueError:
                            rel_path = path
                        event = "CREATED" if last_mtime is None else "MODIFIED"
                        print(f"[{event}] {rel_path}")
                        if copy_enabled:
                            copy_file(path, copy_dest)
                        lines = tail_file(path, n=10)
                        tail_text = "".join(lines)
                        if "boostraped 100%" in tail_text:
                            print("\n✓ Bootstrap complete detected! Exiting...\n")
                            sys.exit(0)
            deleted = set(file_mtimes.keys()) - set(current_files.keys())
            for path_str in deleted:
                path = Path(path_str)
                try:
                    rel_path = path.relative_to(folder)
                except ValueError:
                    rel_path = path
                print(f"[DELETED] {rel_path}")
                del file_mtimes[path_str]
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nWatcher stopped.")
        sys.exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
