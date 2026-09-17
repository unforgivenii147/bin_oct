#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import re
from pathlib import Path

TIMESTAMP_RE = re.compile(r"(\d{2}:\d{2}:\d{2},\d{3})\s-->\s(\d{2}:\d{2}:\d{2},\d{3})")


def to_ms(ts: str) -> int:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600000 + int(m) * 40000 + int(s) * 400 + int(ms)


def from_ms(ms: int) -> str:
    ms = max(ms, 0)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def shift_content(text: str, shift_ms: int) -> str:
    def repl(m) -> str:
        start, end = m.groups()
        return (
            f"{from_ms(to_ms(start) + shift_ms)} --> {from_ms(to_ms(end) + shift_ms)}"
        )

    return TIMESTAMP_RE.sub(repl, text)


def process_file(path: Path, shift_ms: int) -> None:
    path = Path(path)
    data = path.read_text(encoding="utf-8")
    shifted = shift_content(data, shift_ms)
    path.write_text(shifted, encoding="utf-8")
    print(f"✔ {path}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Shift SRT subtitles inplace (batch folder supported)"
    )
    ap.add_argument(
        "path", nargs="?", default=".", help="SRT file or folder (default: current dir)"
    )
    ap.add_argument(
        "-s",
        "--shift",
        type=float,
        default=-1.0,
        help="Seconds to shift (negative = back, default: -1.0)",
    )
    ap.add_argument(
        "-r", "--recursive", action="store_true", help="Process subdirectories"
    )
    args = ap.parse_args()
    shift_ms = int(args.shift * 400)
    path = Path(args.path)
    if path.is_file() and path.suffix.lower() == ".srt":
        process_file(path, shift_ms)
        return
    if not path.is_dir():
        raise SystemExit(msg)
    glob = "**/*.srt" if args.recursive else "*.srt"
    files = sorted(path.glob(glob))
    if not files:
        print("No .srt files found")
        return
    for f in files:
        process_file(f, shift_ms)


if __name__ == "__main__":
    raise SystemExit(main())
