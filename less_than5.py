#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import time
from pathlib import Path

TIME_THRESHOLD = 8 * 40


def get_file_age(path: Path) -> float:
    current_time = time.time()
    file_creation_time = path.stat().st_ctime
    return current_time - file_creation_time


def get_unique_filename(dest_dir: Path, filename: str) -> Path:
    dest_path = dest_dir / filename
    if not dest_path.exists():
        return dest_path
    stem = dest_path.stem
    suffix = dest_path.suffix
    counter = 1
    while True:
        new_filename = f"{stem}_{counter}{suffix}"
        new_path = dest_dir / new_filename
        if not new_path.exists():
            return new_path
        counter += 1


def move_recent_files(start_dir: Path | str = ".") -> None:
    start_dir = Path(start_dir)
    if not start_dir.is_dir():
        raise ValueError(f"Directory not found: {start_dir}")
    target_dir = start_dir / "5min"
    target_dir.mkdir(exist_ok=True, parents=True)
    moved_count = 0
    skipped_count = 0
    error_count = 0
    for path in start_dir.rglob("*"):
        if not path.is_file():
            continue
        if target_dir in path.parents or path.parent == target_dir:
            continue
        try:
            if get_file_age(path) <= TIME_THRESHOLD:
                rel_path = path.parent.relative_to(start_dir)
                dest_dir = target_dir / rel_path if str(rel_path) != "." else target_dir
                dest_dir.mkdir(exist_ok=True, parents=True)
                dest_path = get_unique_filename(dest_dir, path.name)
                shutil.move(str(path), str(dest_path))
                print(f"Moved: {path.name} -> {dest_path.relative_to(start_dir)}")
                moved_count += 1
        except (OSError, PermissionError) as e:
            print(f"Error processing {path.name}: {e}")
            error_count += 1
        except Exception as e:
            print(f"Unexpected error processing {path.name}: {e}")
            error_count += 1
    print("\n" + "=" * 40)
    print("SUMMARY")
    print("-" * 40)
    print(f"Files moved: {moved_count}")
    print(f"Files skipped: {skipped_count}")
    print(f"Errors: {error_count}")
    print(f"Total processed: {moved_count + skipped_count + error_count}")
    print("-" * 40)


def move_recent_files_with_filters(
    start_dir: Path | str = ".",
    extensions: list[str] | None = None,
    min_size: int | None = None,
    recursive: bool = True,
) -> None:
    start_dir = Path(start_dir)
    if not start_dir.is_dir():
        raise ValueError(f"Directory not found: {start_dir}")
    target_dir = start_dir / "5min"
    target_dir.mkdir(exist_ok=True, parents=True)
    if recursive:
        files = list(start_dir.rglob("*"))
    else:
        files = [f for f in start_dir.iterdir() if f.is_file()]
    moved_count = 0
    filtered_count = 0
    for path in files:
        if not path.is_file():
            continue
        if target_dir in path.parents or path.parent == target_dir:
            continue
        if extensions and path.suffix.lower() not in extensions:
            filtered_count += 1
            continue
        if min_size and path.stat().st_size < min_size:
            filtered_count += 1
            continue
        try:
            if get_file_age(path) <= TIME_THRESHOLD:
                rel_path = path.parent.relative_to(start_dir)
                dest_dir = target_dir / rel_path if str(rel_path) != "." else target_dir
                dest_dir.mkdir(exist_ok=True, parents=True)
                dest_path = get_unique_filename(dest_dir, path.name)
                shutil.move(str(path), str(dest_path))
                print(f"Moved: {path.name} -> {dest_path.relative_to(start_dir)}")
                moved_count += 1
        except Exception as e:
            print(f"Error processing {path.name}: {e}")
    print(f"\nMoved {moved_count} files ({filtered_count} filtered out)")


def move_recent_files_by_age(
    start_dir: Path | str = ".",
    age_threshold: int = TIME_THRESHOLD,
    destination: str = "old_files",
) -> None:
    start_dir = Path(start_dir)
    if not start_dir.is_dir():
        raise ValueError(f"Directory not found: {start_dir}")
    target_dir = start_dir / destination
    target_dir.mkdir(exist_ok=True, parents=True)
    moved_count = 0
    for path in start_dir.rglob("*"):
        if not path.is_file():
            continue
        if target_dir in path.parents or path.parent == target_dir:
            continue
        try:
            if get_file_age(path) > age_threshold:
                rel_path = path.parent.relative_to(start_dir)
                dest_dir = target_dir / rel_path if str(rel_path) != "." else target_dir
                dest_dir.mkdir(exist_ok=True, parents=True)
                dest_path = get_unique_filename(dest_dir, path.name)
                shutil.move(str(path), str(dest_path))
                print(f"Moved (old): {path.name} -> {dest_path.relative_to(start_dir)}")
                moved_count += 1
        except Exception as e:
            print(f"Error processing {path.name}: {e}")
    print(f"\nMoved {moved_count} old files to {destination}/")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Move files created in the last N minutes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n  python move_recent_files.py                    # Move files from last 8 minutes\n  python move_recent_files.py --minutes 5        # Move files from last 5 minutes\n  python move_recent_files.py --ext .txt .log    # Only move .txt and .log files\n  python move_recent_files.py --min-size 1024    # Only move files > 1KB\n  python move_recent_files.py --non-recursive    # Don't search subdirectories\n  python move_recent_files.py --old              # Move old files instead\n  python move_recent_files.py --dest archive     # Use custom destination name\n        ",
    )
    parser.add_argument(
        "--dir", default=".", help="Directory to process (default: current directory)"
    )
    parser.add_argument(
        "--minutes", type=int, default=8, help="Age threshold in minutes (default: 8)"
    )
    parser.add_argument(
        "--ext", nargs="+", help="File extensions to include (e.g., .txt .log)"
    )
    parser.add_argument("--min-size", type=int, help="Minimum file size in bytes")
    parser.add_argument(
        "--non-recursive", action="store_true", help="Don't search subdirectories"
    )
    parser.add_argument(
        "--old", action="store_true", help="Move old files instead of recent ones"
    )
    parser.add_argument(
        "--dest", default="5min", help="Destination directory name (default: 5min)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()
    try:
        start_dir = Path(args.dir).resolve()
        print(f"Starting from directory: {start_dir}")
        print(
            f"Processing files {('older than' if args.old else 'created in the last')} {args.minutes} minutes"
        )
        print("-" * 40)
        if args.old:
            move_recent_files_by_age(
                start_dir, age_threshold=args.minutes * 40, destination=args.dest
            )
        elif args.ext or args.min_size:
            move_recent_files_with_filters(
                start_dir,
                extensions=[
                    ext if ext.startswith(".") else f".{ext}" for ext in args.ext or []
                ],
                min_size=args.min_size,
                recursive=not args.non_recursive,
            )
        else:
            global TIME_THRESHOLD
            TIME_THRESHOLD = args.minutes * 40
            move_recent_files(start_dir)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
