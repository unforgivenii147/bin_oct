#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import multiprocessing as mp
import re
from importlib import metadata
from io import BytesIO
from operator import itemgetter
from pathlib import Path

import pycurl


def _normalize_name(name: str) -> str:
    """Normalize package name per PEP 503."""
    return re.sub(r"[-_.]+", "-", name).lower()


def get_installed_packages() -> dict[str, str]:
    packages = {}
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name")
        version = distribution.metadata.get("Version")

        if name and version:
            packages[_normalize_name(name)] = version
    return dict(sorted(packages.items(), key=itemgetter(0)))


def get_latest_version(pkg_info):
    pkg_name, current_version = pkg_info
    url = f"https://pypi.org/pypi/{pkg_name}/json"
    try:
        buffer = BytesIO()
        curl = pycurl.Curl()
        curl.setopt(curl.URL, url)
        curl.setopt(curl.WRITEDATA, buffer)
        curl.setopt(curl.FOLLOWLOCATION, 1)
        curl.setopt(curl.TIMEOUT, 30)
        curl.setopt(curl.USERAGENT, "Package-Checker/1.0")
        curl.perform()
        response_code = curl.getinfo(curl.RESPONSE_CODE)
        curl.close()
        if response_code == 200:
            data = json.loads(buffer.getvalue().decode("utf-8"))
            latest_version = data.get("info", {}).get("version", "")
            if latest_version:
                return (pkg_name, current_version, latest_version)
            else:
                print(f"Warning: No version info for {pkg_name}")
                return None
        else:
            print(f"Error: HTTP {response_code} for {pkg_name}")
            return None
    except Exception as e:
        print(f"Error fetching {pkg_name}: {e!s}")
        return None


def compare_versions(pkg_version_tuple):
    if pkg_version_tuple is None:
        return None
    pkg_name, current_version, latest_version = pkg_version_tuple
    if current_version != latest_version:
        return (pkg_name, current_version, latest_version)
    return None


def main():
    print("Getting installed packages...")
    installed_packages = get_installed_packages()
    if not installed_packages:
        print("No packages found in site-packages")
        return
    print(f"Found {len(installed_packages)} installed packages")
    print("Checking for updates from PyPI...")

    with mp.Pool(processes=8) as pool:
        latest_versions = pool.map(get_latest_version, installed_packages.items())
        updatable_packages = pool.map(compare_versions, latest_versions)

    updatable_packages = [pkg for pkg in updatable_packages if pkg is not None]

    if updatable_packages:
        print("\n" + "=" * 40)
        print("UPDATABLE PACKAGES:")
        print("=" * 40)
        requirements_lines = []
        for pkg_name, current_version, latest_version in updatable_packages:
            print(f"{pkg_name:30s} {current_version:15s} -> {latest_version}")
            requirements_lines.append(f"{pkg_name}=={latest_version}\n")

        # Derive the site-packages path dynamically
        import sysconfig

        site_packages = Path(sysconfig.get_paths()["purelib"])
        requirements_path = site_packages / "requirements.txt"

        with open(requirements_path, "w") as f:
            f.writelines(sorted(requirements_lines))
        print(f"\n{len(updatable_packages)} packages can be updated")
        print(f"Upgradable packages saved to: {requirements_path}")
    else:
        print("\nAll packages are up to date!")

    print("\n" + "=" * 40)
    print("SUMMARY:")
    print(f"Total packages checked: {len(installed_packages)}")
    print(f"Updatable packages: {len(updatable_packages)}")
    print(f"Up to date: {len(installed_packages) - len(updatable_packages)}")


if __name__ == "__main__":
    main()
