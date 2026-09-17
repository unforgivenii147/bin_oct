#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import subprocess
import sys


def get_all_packages():
    try:
        result = subprocess.run(
            ["pkg", "list-all"], capture_output=True, text=True, check=True
        )
        packages = []
        lines = result.stdout.split("\n")
        for line in lines:
            if (
                line
                and not line.startswith("Listing")
                and not line.startswith("Packages")
            ):
                parts = line.split("/")[0].split()
                if parts:
                    packages.append(parts[0])
        return packages
    except subprocess.CalledProcessError:
        try:
            result = subprocess.run(
                ["apt", "list", "--installed"], capture_output=True, text=True
            )
            packages = []
            for line in result.stdout.split("\n"):
                if "/" in line:
                    pkg_name = line.split("/")[0]
                    packages.append(pkg_name)
            return packages
        except:
            return []


def search_packages(pattern: str):
    all_packages = get_all_packages()
    regex_pattern = pattern.replace("*", ".*").replace("?", ".")
    regex = re.compile(regex_pattern, re.IGNORECASE)
    matches = [pkg for pkg in all_packages if regex.search(pkg)]
    return matches


def install_packages(packages) -> bool:
    if not packages:
        print("No packages to install.")
        return False
    print(f"\nFound {len(packages)} package(s) to install:")
    for pkg in packages:
        print(f"  - {pkg}")
    response = input("\nDo you want to install these packages? (y/N): ").lower()
    if response != "y":
        print("Installation cancelled.")
        return False
    try:
        subprocess.run(["pkg", "install"] + packages, check=True)
        print("\n✓ Installation completed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n✗ Installation failed: {e}")
        return False


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python install_wildcard.py <pattern>")
        print("Examples:")
        print(
            "  python install_wildcard.py morse     # Install packages with 'morse' in name"
        )
        print(
            "  python install_wildcard.py python*   # Install packages starting with 'python'"
        )
        print(
            "  python install_wildcard.py *sql*     # Install packages containing 'sql'"
        )
        sys.exit(1)
    pattern = sys.argv[1]
    print(f"Searching for packages matching '{pattern}'...")
    matches = search_packages(pattern)
    if matches:
        install_packages(matches)
    else:
        print(f"No packages found matching pattern '{pattern}'")


if __name__ == "__main__":
    raise SystemExit(main())
