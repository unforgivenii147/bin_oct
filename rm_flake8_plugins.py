#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import subprocess
import sys
from importlib import metadata


def get_installed_flake8_plugins():
    plugins = []
    for dist in metadata.distributions():
        try:
            entry_points = dist.entry_points
            flake8_entry_points = [
                ep
                for ep in entry_points
                if ep.group in ("flake8.extension", "flake8.report")
            ]
            if flake8_entry_points:
                plugins.append(dist.metadata["Name"])
                continue
            if re.match(r"^flake8-", dist.metadata["Name"], re.IGNORECASE):
                plugins.append(dist.metadata["Name"])
        except Exception as e:
            try:
                if re.match(r"^flake8-", dist.metadata["Name"], re.IGNORECASE):
                    plugins.append(dist.metadata["Name"])
            except:
                pass
    return sorted(set(plugins))


def uninstall_packages(packages, dry_run=False):
    if not packages:
        print("No flake8 plugins found to uninstall.")
        return
    print(f"\nFound {len(packages)} flake8 plugin(s) to uninstall:")
    for pkg in packages:
        print(f"  - {pkg}")
    if dry_run:
        print("\nDry run mode - no packages will be uninstalled.")
        return
    response = input("\nDo you want to proceed with uninstallation? (yes/no): ")
    if response.lower() not in ["yes", "y"]:
        print("Uninstallation cancelled.")
        return
    for pkg in packages:
        print(f"\nUninstalling {pkg}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "uninstall", "-y", pkg])
            print(f"✓ Successfully uninstalled {pkg}")
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to uninstall {pkg}: {e}")
        except Exception as e:
            print(f"✗ Error uninstalling {pkg}: {e}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Uninstall all flake8 plugins")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be uninstalled without actually uninstalling",
    )
    args = parser.parse_args()
    print("Scanning for flake8 plugins...")
    plugins = get_installed_flake8_plugins()
    plugins = [p for p in plugins if p.lower() != "flake8"]
    uninstall_packages(plugins, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
