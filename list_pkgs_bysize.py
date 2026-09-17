#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import subprocess

from dh import fsz


def get_packages_with_size():
    try:
        result = subprocess.run(
            ["apt", "list", "--installed"], capture_output=True, text=True
        )
        packages = []
        for line in result.stdout.split("\n"):
            if line and not line.startswith("Listing"):
                parts = line.split()
                if parts:
                    pkg_name = parts[0].split("/")[0]
                    packages.append(pkg_name)
        pkg_sizes = []
        for pkg in packages:
            try:
                info = subprocess.run(
                    ["apt", "show", pkg], capture_output=True, text=True
                )
                for line in info.stdout.split("\n"):
                    if line.startswith("Installed-Size:"):
                        size_kb = int(re.search(r"\d+", line).group())
                        pkg_sizes.append((pkg, size_kb * 1024))
                        break
            except:
                continue
        return sorted(pkg_sizes, key=lambda x: x[1], reverse=True)
    except Exception as e:
        print(f"Error: {e}")
        return []


def main():
    print("Fetching package sizes...")
    packages = get_packages_with_size()
    if not packages:
        print("No packages found or error occurred")
        return
    print("\n" + "=" * 40)
    print(f"{'Package':<30} {'Size':>20}")
    print("-" * 40)
    total = 0
    for pkg, size in packages:
        print(f"{pkg:<30} {fsz(size):>20}")
        total += size
    print("-" * 40)
    print(f"{'TOTAL':<30} {fsz(total):>20}")


if __name__ == "__main__":
    raise SystemExit(main())
