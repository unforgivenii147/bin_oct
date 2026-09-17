#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
from pathlib import Path

from dh import get_nobinary, get_random_filename, should_skip


def read_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return None


def get_file_extension(path: Path) -> str:
    return path.suffix.lstrip(".").lower()


def merge_files_by_type(
    files: list[Path],
    cwd: Path,
    ext_filter: list[str] | None = None,
    group_by_ext: bool = False,
) -> list[Path]:
    if ext_filter:
        ext_filter = [e.lower() for e in ext_filter]
        files = [f for f in files if get_file_extension(f).lower() in ext_filter]
    valid_files = []
    for path in files:
        if should_skip(path):
            continue
        content = read_file(path)
        if content is not None and content.strip():
            valid_files.append((path, content))
    if not valid_files:
        print("ℹ️  No files to merge.")
        return []
    if not group_by_ext:
        output_file = cwd / f"{get_random_filename()}.txt"
        extensions = {get_file_extension(f) for f, _ in valid_files}
        if len(extensions) == 1 and ext_filter is None:
            ext = next(iter(extensions))
            if ext:
                output_file = cwd / f"{get_random_filename()}.{ext}"
        write_merged_file(output_file, valid_files, cwd)
        return [output_file]
    else:
        output_dir = cwd / "merged"
        output_dir.mkdir(exist_ok=True)
        ext_groups: dict[str, list[tuple[Path, str]]] = {}
        for path, content in valid_files:
            ext = get_file_extension(path)
            if ext not in ext_groups:
                ext_groups[ext] = []
            ext_groups[ext].append((path, content))
        output_files = []
        for ext, group_files in ext_groups.items():
            output_file = (
                output_dir / f"{get_random_filename()}.{ext}"
                if ext
                else output_dir / f"{get_random_filename()}.txt"
            )
            write_merged_file(output_file, group_files, cwd)
            output_files.append(output_file)
        return output_files


def write_merged_file(
    output_file: Path, files_content: list[tuple[Path, str]], cwd: Path
) -> None:
    try:
        total_size = 0
        file_count = 0
        with output_file.open("w", encoding="utf-8") as fo:
            for path, content in files_content:
                relative_path = path.relative_to(cwd)
                fo.write(f"# File: {relative_path}\n")
                fo.write(content)
                if not content.endswith("\n"):
                    fo.write("\n")
                total_size += len(content)
                file_count += 1
        print(
            f"✅ Merged {file_count} files ({total_size:,} bytes) into: {output_file}"
        )
    except OSError as e:
        print(f"❌ Error writing output file {output_file}: {e}")
        if output_file.exists():
            output_file.unlink()


def merge_files(args: argparse.Namespace) -> None:
    cwd = Path.cwd()
    files = [f for f in get_nobinary(cwd)]
    if not args.group:
        pass
    if args.extensions:
        print(f"🔍 Filtering for extensions: {', '.join(args.extensions)}")
    output_files = merge_files_by_type(
        files, cwd, ext_filter=args.extensions, group_by_ext=args.group
    )
    if not output_files:
        print("ℹ️  No content to merge (all files were empty or skipped).")
    if args.group and output_files:
        print(f"📁 All merged files saved in: {cwd / 'merged'}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge text files in the current directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python merger.py                    # Merge all non-binary files
  python merger.py -e py cpp          # Merge only .py and .cpp files
  python merger.py -c                 # Group files by extension into separate files
  python merger.py -c -e py cpp       # Group .py and .cpp files by extension
        """,
    )
    parser.add_argument(
        "-e",
        "--extensions",
        nargs="+",
        help="File extensions to merge (e.g., py cpp js)",
    )
    parser.add_argument(
        "-c",
        "--group",
        action="store_true",
        help='Group files by extension, output multiple files in "merged" directory',
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    merge_files(args)
