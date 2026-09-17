#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import re
from pathlib import Path

from dh import colored

VIDEO_EXTS = {".srt"}
LEADING_JUNK = re.compile(r"^\s*[\d\s\.-]{6,}", re.IGNORECASE)
EPISODE_PATTERNS = [
    re.compile(r"S\d{2}E(\d{2})", re.IGNORECASE),
    re.compile(r"(\d{1,2})x(\d{2})", re.IGNORECASE),
]
TRASH = re.compile(
    r"(HDTV|WEB[-\. ]?DL|WEBRIP|BLURAY|IMOVIE[-\. ]?DL|ELKA|PARISA|KILLERS|FUM|TURBO|FA)",
    re.IGNORECASE,
)


def extract_episode(name: str):
    for pat in EPISODE_PATTERNS:
        m = pat.search(name)
        if m:
            return m.group(m.lastindex)
    return None


def clean_name(fname: str) -> str | None:
    name = LEADING_JUNK.sub("", fname)
    ep = extract_episode(name)
    if not ep:
        return None
    return f"E{ep.zfill(2)}"


def collect_files(path: Path, recursive: bool) -> list[Path]:
    if recursive:
        return [p for p in path.rglob("*") if p.suffix.lower() in VIDEO_EXTS]
    return [p for p in path.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS]


def main() -> None:
    ap = argparse.ArgumentParser("Subtitle cleaner")
    ap.add_argument("-r", "--recursive", action="store_true")
    ap.add_argument("-w", "--write", action="store_true")
    args = ap.parse_args()
    files = collect_files(Path(), args.recursive)
    if not files:
        print("No subtitle files found")
        return
    print(colored("\nPreview:", "cyan", attrs=["bold"]))
    for f in files:
        new_core = clean_name(f.name)
        if not new_core:
            print(colored("SKIP:", "yellow"), f.name)
            continue
        new_name = new_core + f.suffix
        target = f.with_name(new_name)
        print(colored("OLD:", "red"), f.name, colored("-> NEW:", "green"), new_name)
        if args.write:
            if target.exists():
                print(colored("  EXISTS, skipped", "yellow"))
            else:
                f.rename(target)
    if not args.write:
        print(colored("\nDry-run only. Use -w to apply.", "yellow"))


if __name__ == "__main__":
    raise SystemExit(main())
