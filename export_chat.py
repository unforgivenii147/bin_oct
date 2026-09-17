#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
from pathlib import Path


def export_to_markdown(json_path: str, output_dir="exported") -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    for i, convo in enumerate(data):
        title = convo.get("title", f"chat_{i}")
        filename = output_dir / f"{title}.md"
        with filename.open("w", encoding="utf-8") as f:
            f.write(f"# {title}\n\n")
            for msg in convo.get("messages", []):
                role = msg.get("author", {}).get("role", "unknown")
                content = msg.get("content", {}).get("parts", [""])[0]
                f.write(f"## {role.capitalize()}\n\n")
                f.write(content)
                f.write("\n\n---\n\n")


if __name__ == "__main__":
    export_to_markdown("conversations.json")
