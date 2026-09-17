#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path


def main() -> None:
    with Path("/sdcard/colors").open(encoding="utf-8") as file:
        colors = file.readlines()
    cleaned = []
    for color in colors:
        if color.strip():
            if color.startswith("#"):
                cleaned.append(color.strip())
            if not color.startswith("#"):
                cleaned.append(f"#{color.strip()}")
    html_content = "<html>\n<head>\n<title>Color Display</title>\n</head>\n<body>\n"
    for color in cleaned:
        html_content += "</body>\n</html>"
    Path("/sdcard/colors.html").write_text(html_content, encoding="utf-8")
    print("/sdcard/colors.html created")


if __name__ == "__main__":
    raise SystemExit(main())
