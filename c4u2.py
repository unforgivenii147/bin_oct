#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import time
from io import BytesIO
from pathlib import Path

import pycurl
from dh import cprint, get_installed_packages
from packaging.version import Version

MAX_WORKERS = 8
TIMEOUT = 15
RESULTS_FILE = "/sdcard/upgradable.json"


def get_latest_version(pkg_name: str) -> str | None:
    url = f"https://pypi.org/pypi/{pkg_name}/json"
    try:
        buffer = BytesIO()
        curl = pycurl.Curl()
        curl.setopt(curl.URL, url)
        curl.setopt(curl.WRITEDATA, buffer)
        curl.setopt(curl.FOLLOWLOCATION, 1)
        curl.setopt(curl.TIMEOUT, TIMEOUT)
        curl.setopt(curl.USERAGENT, "Package-Updater/1.0")
        curl.setopt(curl.SSL_VERIFYPEER, 1)
        curl.setopt(curl.SSL_VERIFYHOST, 2)
        curl.perform()
        response_code = curl.getinfo(curl.RESPONSE_CODE)
        curl.close()
        if response_code != 200:
            return None
        data = json.loads(buffer.getvalue().decode("utf-8"))
        latest_version = data.get("info", {}).get("version", "")
        if latest_version:
            print(f"{pkg_name}:{latest_version}")
            return latest_version
        else:
            return None
    except Exception as e:
        return None


def load_previous_results() -> dict[str, dict]:
    if Path(RESULTS_FILE).exists():
        try:
            with Path(RESULTS_FILE).open(encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            cprint(
                f"Warning: Corrupted results file '{RESULTS_FILE}'. Starting fresh.",
                "red",
            )
            return {}
    return {}


def save_results(results: dict[str, dict]) -> None:
    with Path(RESULTS_FILE).open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)


if __name__ == "__main__":
    start_time = time.time()
    installed_packages = get_installed_packages()
    total_packages = len(installed_packages)
    cprint(f"Found {total_packages} installed packages.", "blue")
    previous_results = load_previous_results()
    current_results = {}
    packages_to_check = []
    for pkg_name, installed_version in installed_packages.items():
        if pkg_name in previous_results:
            prev_data = previous_results[pkg_name]
            if (
                prev_data.get("latest_version")
                and prev_data.get("latest_version") == "null"
            ):
                packages_to_check.append((pkg_name, installed_version))
                continue
            if prev_data.get("installed_version") == installed_version:
                current_results[pkg_name] = prev_data
                continue
        packages_to_check.append((pkg_name, installed_version))
    cprint(f"Will check {len(packages_to_check)} packages.", "blue")
    updatable_pkgs_info: list[tuple[str, str, str]] = []
    for i, (pkg_name, installed_version) in enumerate(packages_to_check):
        latest_version_str = get_latest_version(pkg_name)
        current_results[pkg_name] = {
            "installed_version": installed_version,
            "latest_version": latest_version_str,
            "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if latest_version_str:
            try:
                installed_ver = Version(installed_version)
                latest_ver = Version(latest_version_str)
                if installed_ver < latest_ver:
                    updatable_pkgs_info.append(
                        (pkg_name, installed_version, latest_version_str)
                    )
                    cprint(
                        f"[{i + 1}/{len(packages_to_check)}] {pkg_name}: {installed_version} -> {latest_version_str} (Updatable!)",
                        "green",
                    )
                else:
                    cprint(
                        f"[{i + 1}/{len(packages_to_check)}] {pkg_name}: {installed_version} (Latest: {latest_version_str})",
                        "white",
                    )
            except Exception as ver_err:
                cprint(
                    f"[{i + 1}/{len(packages_to_check)}] {pkg_name}: Could not parse versions '{installed_version}' or '{latest_version_str}': {ver_err}",
                    "yellow",
                )
        else:
            cprint(
                f"[{i + 1}/{len(packages_to_check)}] {pkg_name}: Could not get latest version from PyPI.",
                "yellow",
            )
        if (i + 1) % 10 == 0 or i + 1 == len(packages_to_check):
            save_results(current_results)
            cprint("Results saved periodically.", "blue")
    cprint("\n--- Summary of Updatable Packages ---", "blue")
    if updatable_pkgs_info:
        for pkg, installed_ver, latest_ver in updatable_pkgs_info:
            cprint(f"{pkg}: {installed_ver} -> {latest_ver}", "magenta")
        cprint(
            f"""
To update these packages, you can use: pip install --upgrade {" ".join([p[0] for p in updatable_pkgs_info])}""",
            "yellow",
        )
    else:
        cprint(
            "All installed packages are up to date or could not be checked.", "green"
        )
    end_time = time.time()
    cprint(f"\nFinished in {end_time - start_time:.2f} seconds.", "blue")
