#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PART_RE = re.compile(r"^(?P<prefix>.+)\.part(?P<num>\d+)$")


def collect_paths(inputs: list[str]) -> list[Path]:
    if not inputs:
        return [
            p for p in Path(".").rglob("*") if p.is_file() and PART_RE.match(p.name)
        ]
    out: list[Path] = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            out.extend(x for x in p.rglob("*") if x.is_file() and PART_RE.match(x.name))
        elif p.is_file():
            out.append(p)
    return out


def group_parts(paths: list[Path]) -> dict[tuple[Path, str], list[tuple[int, Path]]]:
    groups: dict[tuple[Path, str], list[tuple[int, Path]]] = {}
    for p in paths:
        m = PART_RE.match(p.name)
        if not m:
            continue
        key = (p.parent.resolve(), m.group("prefix"))
        groups.setdefault(key, []).append((int(m.group("num")), p))
    return groups


def merge_group(items: tuple[tuple[Path, str], list[tuple[int, Path]]]) -> Path:
    (parent, prefix), parts = items
    parts.sort(key=lambda x: x[0])
    out = parent / prefix
    with out.open("wb") as dst:
        for _, part in parts:
            with part.open("rb") as src:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    dst.write(chunk)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    paths = collect_paths(args.paths)
    groups = group_parts(paths)
    if not groups:
        raise SystemExit("No .part files found")
    with ThreadPoolExecutor() as ex:
        outputs = list(ex.map(merge_group, groups.items()))
    for out in outputs:
        print(out)


if __name__ == "__main__":
    raise SystemExit(main())
