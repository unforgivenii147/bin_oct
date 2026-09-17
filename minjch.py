#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import multiprocessing
import os
import re
from pathlib import Path

from rcssmin import cssmin


def minify_html(html: str) -> str:
    html = re.sub(r">\s+<", "><", html)
    html = re.sub(r"\s{2,}", " ", html)
    return html.strip()


def process_file(path: str) -> str:
    path = Path(path)
    try:
        ext = os.path.splitext(path)[1].lower()
        content = Path(path).read_text(encoding="utf-8")
        if ext == ".css":
            content = cssmin(content)
        elif ext == ".json":
            parsed = json.loads(content)
            content = json.dumps(parsed, separators=(",", ":"))
        elif ext in {".html", ".htm"}:
            content = minify_html(content)
        else:
            return f"SKIP → {path}"
        Path(path).write_text(content, encoding="utf-8")
        return f"OK → {path}"
    except Exception as e:
        return f"ERR ({path}): {e}"


def collect_files() -> list:
    supported = ".css", ".json", ".html", ".htm"
    out = []
    for base, _, files in os.walk(Path.cwd()):
        for name in files:
            path = os.path.join(base, name)
            lower = name.lower()
            if lower.endswith(supported):
                out.append(path)
    return out


def main() -> None:
    files = collect_files()
    if not files:
        print("No supported files found.")
        return
    print(f"Found {len(files)} files. Starting multiprocessing...")
    with multiprocessing.Pool(multiprocessing.cpu_count()) as pool:
        for result in pool.imap_unordered(process_file, files):
            print(result)


if __name__ == "__main__":
    raise SystemExit(main())
