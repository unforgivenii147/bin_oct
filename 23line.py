#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

EXT = {".py", ".h", ".c", ".cpp", ".cc", ".cxx", ".hh", ".hpp", ".hxx"}


def get_first_13(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines(
            keepends=True
        )
        return "".join(lines[:23])
    except OSError:
        return ""


def main() -> None:
    output_path = Path("all.txt").resolve()
    collected = []
    for path in Path.cwd().rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in EXT:
            continue
        if path.resolve() == output_path:
            continue
        snippet = get_first_13(path)
        if snippet:
            collected.append(snippet)
    unique_collected = list(set(collected))
    output_path.write_text("\n\n\n".join(unique_collected), encoding="utf-8")
    print(f"Unique snippets saved → {output_path}")
    print(f"Total unique blocks: {len(unique_collected)}")


if __name__ == "__main__":
    raise SystemExit(main())
