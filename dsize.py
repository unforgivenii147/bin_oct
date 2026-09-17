#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import urllib.error
import urllib.request
from pathlib import Path

from dh import fsz


def fetch_content_length(url: str) -> int | None:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            length = response.headers.get("Content-Length")
            if length:
                return int(length)
    except urllib.error.HTTPError as e:
        if e.code not in {405, 403}:
            raise
    request = urllib.request.Request(url, method="GET")
    request.add_header("Range", "bytes=0-0")
    with urllib.request.urlopen(request, timeout=10) as response:
        length = response.headers.get("Content-Length")
        return int(length) if length else None


def process_url(url: str) -> str:
    try:
        size = fetch_content_length(url)
        print(f"{url[:25]}:{size / (1024 * 1024)} mb")
        if size is None:
            return f"{url}\tUnknown"
        return f"{url}\t{fsz(size)}"
    except Exception as exc:
        return f"{url}\tError: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show download size of a URL or URLs from a file"
    )
    parser.add_argument("input", help="Download URL or file containing URLs")
    args = parser.parse_args()
    input_path = Path(args.input)
    if input_path.is_file():
        lines = input_path.read_text(encoding="utf-8").splitlines()
        updated_lines = [process_url(line.strip()) for line in lines if line.strip()]
        input_path.write_text("\n".join(updated_lines), encoding="utf-8")
        print(f"Updated file: {input_path} ({len(updated_lines)} URLs processed)")
    else:
        print(process_url(args.input))


if __name__ == "__main__":
    raise SystemExit(main())
