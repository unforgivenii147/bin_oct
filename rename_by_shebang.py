#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

SHEBANG_MAPPING = {
    "#!/data/data/com.termux/files/usr/bin/python3?": ".py",
    "#!/data/data/com.termux/files/usr/bin/env python3?": ".py",
    "#!/usr/bin/env python": ".py",
    "#!/usr/bin/python": ".py",
    "#!/data/data/com.termux/files/usr/bin/env sh": ".sh",
    "#!/data/data/com.termux/files/usr/bin/bash": ".sh",
    "#!/data/data/com.termux/files/usr/bin/sh": ".sh",
    "#!/data/data/com.termux/files/usr/bin/env bash": ".sh",
    "#!/usr/bin/env bash": ".sh",
    "#!/bin/bash": ".sh",
    "#!/bin/sh": ".sh",
    "#!/data/data/com.termux/files/usr/bin/node": ".js",
    "#!/data/data/com.termux/files/usr/bin/env node": ".js",
    "#!/usr/bin/env node": ".js",
    "#!/usr/bin/node": ".js",
    "#!/data/data/com.termux/files/usr/bin/ruby": ".rb",
    "#!/data/data/com.termux/files/usr/bin/env ruby": ".rb",
    "#!/usr/bin/env ruby": ".rb",
    "#!/usr/bin/ruby": ".rb",
    "#!/data/data/com.termux/files/usr/bin/perl": ".pl",
    "#!/data/data/com.termux/files/usr/bin/env perl": ".pl",
    "#!/usr/bin/env perl": ".pl",
    "#!/usr/bin/perl": ".pl",
    "#!/data/data/com.termux/files/usr/bin/lua": ".lua",
    "#!/data/data/com.termux/files/usr/bin/env lua": ".lua",
    "#!/usr/bin/env lua": ".lua",
    "#!/usr/bin/lua": ".lua",
    "#!/data/data/com.termux/files/usr/bin/php": ".php",
    "#!/data/data/com.termux/files/usr/bin/env php": ".php",
    "#!/usr/bin/env php": ".php",
    "#!/usr/bin/php": ".php",
    "#!/data/data/com.termux/files/usr/bin/Rscript": ".r",
    "#!/usr/bin/env Rscript": ".r",
    "#!/usr/bin/Rscript": ".r",
    "#!/data/data/com.termux/files/usr/bin/fish": ".fish",
    "#!/data/data/com.termux/files/usr/bin/env fish": ".fish",
    "#!/usr/bin/env fish": ".fish",
    "#!/usr/bin/fish": ".fish",
    "#!/usr/bin/awk": ".awk",
    "#!/usr/bin/env awk": ".awk",
    "#!/usr/bin/sed": ".sed",
}


def get_shebang(path: Path) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            first_line = f.readline().strip()
            if first_line.startswith("#!"):
                return first_line
    except (OSError, UnicodeDecodeError):
        pass
    return None


def get_extension_from_shebang(shebang: str) -> str | None:
    for pattern, extension in SHEBANG_MAPPING.items():
        if re.match(pattern, shebang):
            return extension
    return None


def rename_file(old_path: Path, new_path: Path) -> bool:
    if old_path == new_path:
        return False
    counter = 1
    original_new_path = new_path
    while new_path.exists():
        stem = original_new_path.stem
        suffix = original_new_path.suffix
        new_path = original_new_path.parent / f"{stem}_{counter}{suffix}"
        counter += 1
    print(f"  🔄 Renaming: {old_path.name} -> {new_path.name}")
    shutil.move(str(old_path), str(new_path))
    return True


def check_termux() -> bool:
    termux_prefix = "/data/data/com.termux/files/usr"
    is_termux = os.path.exists(termux_prefix)
    if is_termux:
        print("📱 Termux environment detected")
        print(f"   Prefix: {termux_prefix}")
        print(
            f"   Python: {os.path.realpath('/data/data/com.termux/files/usr/bin/python3')}"
        )
    else:
        print("💻 Standard Linux/Unix environment detected")
    return is_termux


def main() -> None:
    cwd = Path.cwd()
    renamed_count = 0
    skipped_count = 0
    unknown_count = 0
    check_termux()
    print(f"📂 Scanning directory: {cwd}\n")
    files = [f for f in cwd.iterdir() if f.is_file()]
    if not files:
        print("No files found in current directory.")
        return
    for path in files:
        if path.name.startswith("."):
            continue
        shebang = get_shebang(path)
        if not shebang:
            continue
        extension = get_extension_from_shebang(shebang)
        if not extension:
            short_shebang = shebang[:50] + "..." if len(shebang) > 50 else shebang
            print(f"❓ Unknown shebang in: {path.name}")
            print(f"   Shebang: {short_shebang}")
            unknown_count += 1
            continue
        old_name = path.stem
        if not path.suffix or path.suffix != extension:
            new_name = f"{old_name}{extension}"
        else:
            skipped_count += 1
            continue
        new_path = path.parent / new_name
        if rename_file(path, new_path):
            renamed_count += 1
    print(f"\n{'=' * 40}")
    print("📊 Summary:")
    print(f"   ✅ Renamed: {renamed_count} file(s)")
    print(f"   ⏭️  Skipped (already correct): {skipped_count} file(s)")
    if unknown_count:
        print(f"   ❓ Unknown shebangs: {unknown_count} file(s)")
    print(f"{'=' * 40}")
    if unknown_count > 0:
        print(
            "\n💡 Tip: You can add new shebang patterns to the SHEBANG_MAPPING dictionary"
        )


def dry_run() -> None:
    cwd = Path.cwd()
    print("🔍 DRY RUN MODE - No files will be renamed\n")
    check_termux()
    print(f"📂 Scanning directory: {cwd}\n")
    for path in cwd.iterdir():
        if not path.is_file() or path.name.startswith("."):
            continue
        shebang = get_shebang(path)
        if not shebang:
            continue
        extension = get_extension_from_shebang(shebang)
        if extension and not path.suffix == extension:
            new_name = f"{path.stem}{extension}"
            print(f"  Would rename: {path.name} -> {new_name}")
    print("\nRun without '--dry-run' to apply changes.")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--dry-run":
        dry_run()
    elif len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("Usage: python rename_by_shebang.py [OPTION]")
        print("Options:")
        print("  --dry-run    Preview changes without renaming")
        print("  --help       Show this help message")
    else:
        response = input(
            "⚠️  This will rename files in the current directory. Continue? (y/N): "
        )
        if response.lower() == "y":
            raise SystemExit(main())
        else:
            print("Operation cancelled.")
