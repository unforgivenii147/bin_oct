#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys

import requests


def check_package(pkg_name):
    url = f"https://pypi.org/pypi/{pkg_name}/json"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        latest = data["info"]["version"]
        for release in data["releases"][latest]:
            if "pure" in release:
                print(f"{pkg_name}: pure={release['pure']}")
                print(f"  Has wheels: {'wheel' in release.get('packagetype', '')}")
                return
    print(f"{pkg_name}: Not found or no pure info")


if __name__ == "__main__":
    pkgs = sys.argv[1:]
    for pkg in pkgs:
        check_package(pkg)
