#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

OUTPUT_FILE = Path("mime_to_ext.json")


def extract_mime_and_extensions(obj):
    results = []
    if isinstance(obj, dict):
        if "mime-type" in obj:
            mt = obj["mime-type"]
            if isinstance(mt, dict):
                mime_type = mt.get("@type")
                glob = mt.get("glob")
                globs = []
                if isinstance(glob, dict):
                    globs = [glob]
                elif isinstance(glob, list):
                    globs = glob
                for g in globs:
                    if isinstance(g, dict):
                        pattern = g.get("@pattern", "")
                        if pattern.startswith("*.") and len(pattern) > 2:
                            ext = "." + pattern[2:]
                            if mime_type:
                                results.append((mime_type, ext))
        for value in obj.values():
            results.extend(extract_mime_and_extensions(value))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(extract_mime_and_extensions(item))
    return results


def build_mime_to_ext(cwd: Path) -> dict[str, list[str]]:
    mime_to_ext = defaultdict(set)
    for json_file in cwd.rglob("*.json"):
        if json_file.resolve() == OUTPUT_FILE.resolve():
            continue
        try:
            with json_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        for mime_type, ext in extract_mime_and_extensions(data):
            mime_to_ext[mime_type].add(ext)
    return {k: sorted(v) for k, v in sorted(mime_to_ext.items())}


def main() -> None:
    cwd = Path()
    mime_to_ext = build_mime_to_ext(cwd)
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(mime_to_ext, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(mime_to_ext)} MIME entries to {OUTPUT_FILE}")


if __name__ == "__main__":
    raise SystemExit(main())
