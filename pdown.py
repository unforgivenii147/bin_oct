#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests


def get_package_url(package_name, version=None):
    url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        releases = data.get("releases", {})
        if not releases:
            raise ValueError(f"No releases found for {package_name}")
        if version:
            if version not in releases:
                raise ValueError(f"Version {version} not found for {package_name}")
            version_data = releases[version]
        else:
            latest_version = data.get("info", {}).get("version")
            version_data = releases.get(latest_version, [])
        if not version_data:
            raise ValueError("No downloadable files found")
        for file_info in version_data:
            if file_info.get("packagetype") == "bdist_wheel":
                return file_info["url"], file_info["filename"]
        for file_info in version_data:
            if file_info.get("packagetype") == "sdist":
                return file_info["url"], file_info["filename"]
        if version_data:
            return version_data[0]["url"], version_data[0]["filename"]
        raise ValueError("No downloadable files found")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching package information: {e}")
        sys.exit(1)


def download_package(url, filename, output_dir="."):
    try:
        output_path = Path(output_dir) / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {filename}...")
        response = requests.get(url, stream=True)
        response.raise_for_status()
        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0
        with output_path.open("wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = downloaded / total_size * 40
                        print(
                            f"\rProgress: {percent:.1f}% ({downloaded}/{total_size} bytes)",
                            end="",
                        )
        print(f"\n✓ Downloaded to: {output_path}")
        return output_path
    except requests.exceptions.RequestException as e:
        print(f"Error downloading package: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Download a Python package from PyPI.org (skips Python version compatibility check)"
    )
    parser.add_argument("package", help="Package name to download")
    parser.add_argument(
        "-v", "--version", help="Specific version to download (default: latest)"
    )
    parser.add_argument(
        "-o",
        "--output",
        default=".",
        help="Output directory (default: current directory)",
    )
    args = parser.parse_args()
    try:
        print(f"Fetching {args.package} (version: {args.version or 'latest'})...")
        download_url, filename = get_package_url(args.package, args.version)
        print(f"Found: {filename}")
        print(f"URL: {download_url}")
        download_package(download_url, filename, args.output)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
