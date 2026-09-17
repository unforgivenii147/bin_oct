#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

from fastwalk import walk_files


def process_file(path: Path) -> bool:
    path = Path(path)
    if not path.exists():
        return False
    print(f"processing  ... {path.name}")
    last_tag_pos = -1
    tags = "</svg>", "</html>", "</body>", "</script>", "</div>"
    content = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            content.append(line)
    for i, line in reversed(list(enumerate(content))):
        for tag in tags:
            idx = line.rfind(tag)
            if idx != -1:
                last_tag_pos = sum(len(content[j]) for j in range(i)) + idx + len(tag)
                break
        if last_tag_pos != -1:
            break
    if last_tag_pos == -1:
        return True
    trimmed = "".join(content)[:last_tag_pos]
    path.write_text(trimmed, encoding="utf-8")
    return True


if __name__ == "__main__":
    cwd = Path().cwd().resolve()
    for pth in walk_files(cwd):
        path = Path(pth)
        if path.suffix in {".html", ".htm", ".svg", ".xml"}:
            process_file(path)
