#!/data/data/com.termux/files/home/.local/bin/python
"""Fetch the latest packages added to PyPI and save their names to a file."""

import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

RSS_URL = "https://pypi.org/rss/packages.xml"
OUTPUT_FILE = Path("latest_pypi_packages.txt")


def fetch_latest_packages(url: str = RSS_URL) -> list[str]:
    """Fetch the PyPI RSS feed and return a list of package names."""
    req = urllib.request.Request(url, headers={"User-Agent": "pypi-latest-fetcher/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()

    root = ET.fromstring(data)
    names: list[str] = []

    # RSS items look like: <item><title>pkgname 1.0.0</title><link>...</link></item>
    for item in root.findall("./channel/item"):
        title = item.findtext("title", default="").strip()
        link = item.findtext("link", default="").strip()

        # Prefer extracting the name from the link: https://pypi.org/project/<name>/
        name = ""
        if "/project/" in link:
            name = link.rstrip("/").rsplit("/project/", 1)[-1]
        elif title:
            # Title is usually "<name> <version>", so strip the trailing version
            name = title.rsplit(" ", 1)[0]

        if name:
            names.append(name)

    return names


def main() -> None:
    packages = fetch_latest_packages()
    OUTPUT_FILE.write_text("\n".join(packages) + "\n", encoding="utf-8")
    print(f"Saved {len(packages)} package names to {OUTPUT_FILE.resolve()}")
    for name in packages:
        print(f"  - {name}")


if __name__ == "__main__":
    main()
