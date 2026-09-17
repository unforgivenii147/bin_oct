#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import re
import shutil
from collections import defaultdict
from pathlib import Path


def normalize_name(path: Path) -> str:
    name = path.name
    name = re.sub(r"(?:\.lua)+$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"_\d+$", "", name)
    name = name.strip().lower()
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"[^\w.-]+", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-._") or "ungrouped"


def unique_destination(destination: Path) -> Path:
    if not destination.exists():
        return destination
    counter = 1
    while True:
        candidate = destination.with_name(
            f"{destination.stem}_{counter}{destination.suffix}"
        )
        if not candidate.exists():
            return candidate
        counter += 1


def find_lua_files(root: Path, script_path: Path) -> list[Path]:
    files = []
    for path in root.rglob("*.lua"):
        if not path.is_file():
            continue
        if path.resolve() == script_path.resolve():
            continue
        files.append(path)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Group recursively collected Lua files into named folders."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually move files. Without this flag, only show planned moves.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Directory to scan. Defaults to the current directory.",
    )
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    script_path = Path(__file__).resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")
    groups: defaultdict[str, list[Path]] = defaultdict(list)
    for path in find_lua_files(root, script_path):
        group_name = normalize_name(path)
        groups[group_name].append(path)
    if not groups:
        print("No Lua files found.")
        return
    for group_name, files in sorted(groups.items()):
        destination_dir = root / group_name
        print(f"\n[{group_name}]")
        if args.apply:
            destination_dir.mkdir(parents=True, exist_ok=True)
        for source in sorted(files):
            destination = destination_dir / source.name
            destination = unique_destination(destination)
            print(f"  {source.relative_to(root)} -> {destination.relative_to(root)}")
            if args.apply:
                shutil.move(str(source), str(destination))
    if not args.apply:
        print("\nDry run only. Use --apply to perform the moves.")


if __name__ == "__main__":
    main()
