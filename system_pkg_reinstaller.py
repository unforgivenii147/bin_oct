#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import sys

from dh import runcmd


def install_package(pkg_name):
    cmd = ["apt", "install", "--reinstall", "-y", pkg_name]
    print(f"Reinstalling: {pkg_name}")
    try:
        res, _txt, _err = runcmd(
            cmd,
            show_output=True,
        )
        if not res:
            print(f"✓ Successfully reinstalled: {pkg_name}")
            return True
        else:
            print(f"✗ Failed to reinstall {pkg_name}")
            print(f"  Error: {result.stderr.strip()}")
            return False
    except:
        print(f"✗ Error reinstalling {pkg_name}")
        return False


def read_package_list(path):
    packages = []
    try:
        with open(path, "r") as f:
            for line in f:
                pkg = line.strip()
                if pkg and not pkg.startswith("#"):
                    packages.append(pkg)
    except FileNotFoundError:
        print(f"Error: File '{path}' not found.")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)
    return packages


def main():
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    else:
        input_file = os.path.expanduser("~/missing.txt")
    print(f"Reading packages from: {input_file}")
    if os.geteuid() != 0:
        print("Warning: This script requires privileges for apt.")
        print("You may be prompted for your password.")
    packages = read_package_list(input_file)
    if not packages:
        print("No packages found in file.")
        sys.exit(0)
    print(f"Found {len(packages)} package(s) to reinstall.")
    print("-" * 40)
    successful = 0
    failed = 0
    for pkg in packages:
        if install_package(pkg):
            successful += 1
        else:
            failed += 1
        print()
    print("-" * 40)
    print(f"Summary: {successful} successful, {failed} failed")
    print("-" * 40)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    raise SystemExit(main())
