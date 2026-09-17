#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import csv
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime

import requests


def fetch_pypi_updates() -> list[dict[str, str]]:
    url = "https://pypi.org/rss/updates.xml"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        namespaces = {
            "atom": "http://www.w3.org/2005/Atom",
            "dc": "http://purl.org/dc/elements/1.1/",
        }
        packages = []
        for item in root.findall(".//item"):
            package_info = {
                "title": item.find("title").text
                if item.find("title") is not None
                else "",
                "link": item.find("link").text if item.find("link") is not None else "",
                "description": item.find("description").text
                if item.find("description") is not None
                else "",
                "pub_date": item.find("pubDate").text
                if item.find("pubDate") is not None
                else "",
                "guid": item.find("guid").text if item.find("guid") is not None else "",
            }
            if package_info["title"]:
                parts = package_info["title"].split()
                if parts:
                    package_info["package_name"] = parts[0]
                    package_info["version"] = parts[1] if len(parts) > 1 else ""
            packages.append(package_info)
        return packages
    except requests.RequestException as e:
        print(f"Error fetching RSS feed: {e}", file=sys.stderr)
        sys.exit(1)
    except ET.ParseError as e:
        print(f"Error parsing XML: {e}", file=sys.stderr)
        sys.exit(1)


def save_to_json(packages: list[dict[str, str]], filename: str) -> None:
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(packages, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(packages)} packages to {filename}")


def save_to_csv(packages: list[dict[str, str]], filename: str) -> None:
    if not packages:
        print("No packages to save", file=sys.stderr)
        return
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=packages[0].keys())
        writer.writeheader()
        writer.writerows(packages)
    print(f"Saved {len(packages)} packages to {filename}")


def save_to_text(packages: list[dict[str, str]], filename: str) -> None:
    with open(filename, "w", encoding="utf-8") as f:
        f.write("PyPI Latest Package Updates\n")
        f.write(f"Fetched at: {datetime.now().isoformat()}\n")
        f.write("=" * 40 + "\n\n")
        for i, pkg in enumerate(packages, 1):
            f.write(f"{i}. {pkg.get('package_name', 'Unknown')}\n")
            f.write(f"   Version: {pkg.get('version', 'N/A')}\n")
            f.write(f"   Published: {pkg.get('pub_date', 'N/A')}\n")
            f.write(f"   Link: {pkg.get('link', 'N/A')}\n")
            f.write(f"   Description: {pkg.get('description', 'N/A')}\n")
            f.write("\n")
    print(f"Saved {len(packages)} packages to {filename}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Fetch latest package updates from PyPI RSS feed"
    )
    parser.add_argument(
        "-o",
        "--output",
        default="pypi_updates.json",
        help="Output filename (default: pypi_updates.json)",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["json", "csv", "txt"],
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "-n",
        "--num-packages",
        type=int,
        default=None,
        help="Number of latest packages to save (default: all)",
    )
    args = parser.parse_args()
    print("Fetching latest packages from PyPI...")
    packages = fetch_pypi_updates()
    if args.num_packages:
        packages = packages[: args.num_packages]
    base_name = args.output.rsplit(".", 1)[0]
    extension_map = {"json": ".json", "csv": ".csv", "txt": ".txt"}
    filename = base_name + extension_map.get(args.format, ".json")
    save_functions = {"json": save_to_json, "csv": save_to_csv, "txt": save_to_text}
    save_functions[args.format](packages, filename)
    print("\nSummary:")
    print(f"  Total packages fetched: {len(packages)}")
    if packages:
        print(
            f"  Latest package: {packages[0].get('package_name', 'Unknown')} v{packages[0].get('version', '?')}"
        )
        print(f"  Latest update time: {packages[0].get('pub_date', 'Unknown')}")


if __name__ == "__main__":
    raise SystemExit(main())
