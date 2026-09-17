#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
from pathlib import Path

import requests
from packaging import tags


def is_pure_python(requires_python):
    return requires_python is None or all(
        tag.interpreter == "py" and tag.abi == "none" and tag.platform == "any"
        for tag in tags.sys_tags()
    )


def get_package_urls(pkg_name):
    url = f"https://pypi.org/pypi/{pkg_name}/json"
    response = requests.get(url)
    if response.status_code != 200:
        msg = f"Failed to fetch package info for {pkg_name}"
        raise ValueError(msg)
    data = response.json()
    releases = data.get("releases", {})
    latest_version = max(releases.keys())
    print(f"latest version : {latest_version}")
    release_files = releases[latest_version]
    return release_files, latest_version


def download_package(pkg_name) -> None:
    release_files, _version = get_package_urls(pkg_name)
    wheel_files = [f for f in release_files if f["packagetype"] == "bdist_wheel"]
    sdist_files = [f for f in release_files if f["packagetype"] == "sdist"]
    pure_python_wheel = None
    for wheel in wheel_files:
        if wheel["python_version"] == "py3" and "any" in wheel["filename"]:
            pure_python_wheel = wheel
            break
    if pure_python_wheel:
        download_url = pure_python_wheel["url"]
        filename = pure_python_wheel["filename"]
    else:
        download_url = sdist_files[0]["url"]
        filename = sdist_files[0]["filename"]
    print(f"Downloading {filename}...")
    response = requests.get(download_url)
    if response.status_code != 200:
        msg = f"Failed to download {filename}"
        raise ValueError(msg)
    Path(filename).write_bytes(response.content)
    print(f"Downloaded {filename}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download a Python package from PyPI.")
    parser.add_argument("pkg_name", help="Name of the package to download")
    args = parser.parse_args()
    download_package(args.pkg_name)
