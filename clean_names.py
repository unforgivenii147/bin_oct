#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import re
from os.path import commonpath
from pathlib import Path

from dh import colored

REGEX_RULES = [
    r"\bOutcast\b",
    r"\bS\d{2}\b",
    r"\b720p\b",
    r"\b1080p\b",
    r"\bBluRay\b",
    r"\bx264\b",
    "-REWARD_HI",
]
EXTENSIONS = {".srt", ".mkv", ".mp4", ".avi"}


def common_prefix(strings):
    return commonpath(strings)


def common_suffix(strings):
    return commonpath([s[::-1] for s in strings])[::-1]


def apply_regex(name) -> str:
    for rule in REGEX_RULES:
        name = re.sub(rule, "", name, flags=re.IGNORECASE)
    return re.sub(r"\.+", ".", name).strip(". ")


def collect_files(path: Path, recursive):
    if recursive:
        return [p for p in path.rglob("*") if p.suffix.lower() in EXTENSIONS]
    return [p for p in path.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS]


def main() -> None:
    ap = argparse.ArgumentParser(description="Clean repeated words from filenames")
    ap.add_argument("-r", "--recursive", action="store_true", help="scan recursively")
    ap.add_argument("-w", "--write", action="store_true", help="actually rename files")
    args = ap.parse_args()
    files = collect_files(Path(), args.recursive)
    if not files:
        print("No matching files found")
        return
    names = [f.name for f in files]
    prefix = common_prefix(names)
    suffix = common_suffix(names)
    print(colored("\nPreview:", "cyan", attrs=["bold"]))
    for f in files:
        name = f.name
        core = name[len(prefix) : len(name) - len(suffix)]
        core = apply_regex(core)
        new_name = f"{f.stem.split('.')[0]}.{core}{f.suffix}"
        new_name = re.sub(r"\.+", ".", new_name)
        if name == new_name:
            continue
        print(colored("OLD:", "red"), name, colored("-> NEW:", "green"), new_name)
        if args.write:
            target = f.with_name(new_name)
            if target.exists():
                print(colored("SKIPPED (exists)", "yellow"), new_name)
            else:
                f.rename(target)
    if not args.write:
        print(colored("\nDry-run only. Use -w to apply changes.", "yellow"))


if __name__ == "__main__":
    raise SystemExit(main())
