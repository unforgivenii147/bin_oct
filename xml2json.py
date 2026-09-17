#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import sys
from pathlib import Path

import xmltodict
from dh import cprint, get_files, mpf3

MAX_QUEUE = 16
REMOVE_ORIG = True


def process_file(path) -> None:
    path = Path(path)
    try:
        jsonpath = path.with_suffix(".json")
        cprint(f"{jsonpath} created.", "cyan")
        xml_content = path.read_text(encoding="utf-8", errors="ignore")
        with jsonpath.open("w") as f:
            data = xmltodict.parse(xml_content)
            json.dump(data, f, ensure_ascii=False, indent=2)
        if path.suffix == ".xml" and REMOVE_ORIG:
            path.unlink()
    except OSError as e:
        print(f"error {e}")


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_files(cwd, ext=[".xml", ".svg"])
    mpf3(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
