#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

meta_tag_pattern = re.compile(r"<meta[^>]*>", re.IGNORECASE)


def remove_meta_tags(path: Path) -> None:
    try:
        html_content = path.read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(html_content, "html.parser")
        metaz = soup.find_all("meta")
        if metaz:
            new_html_content = meta_tag_pattern.sub("", html_content)
        if new_html_content != html_content:
            path.write_text(new_html_content, encoding="utf-8")
            print(f"Removed meta tags from: {path}")
        else:
            print(f"No meta tags found or removed in: {path}")
    except Exception as e:
        print(f"Error processing {path}: {e}")


def process_directory(directory: Path) -> None:
    for item in directory.rglob("*.html"):
        if item.is_file():
            remove_meta_tags(item)


if __name__ == "__main__":
    cwd = Path()
    print(f"""Starting to remove meta tags from HTML files in '{cwd.resolve()}' and its subdirectories...
""")
    process_directory(cwd)
    print(
        "\nFinished processing. Meta tags have been removed from applicable HTML files."
    )
