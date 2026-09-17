#!/data/data/com.termux/files/home/.local/bin/python
import importlib.metadata
import json
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from packaging import version


class PackageUpdateChecker:
    def __init__(self):
        self.output_dir = Path.home() / ".package_updates"
        self.output_dir.mkdir(exist_ok=True)
        self.txt_file = self.output_dir / "updates.txt"
        self.json_file = self.output_dir / "updates_state.json"
        self.processed_packages: dict[str, dict] = {}
        self.interrupted = False
        signal.signal(signal.SIGINT, self.signal_handler)
        self.load_state()

    def signal_handler(self, sig, frame):
        print("\n\n⚠️  Interrupt received! Saving progress...")
        self.interrupted = True
        self.save_state()
        print(f"✅ Progress saved to {self.json_file}")
        sys.exit(0)

    def load_state(self):
        if self.json_file.exists():
            try:
                with open(self.json_file, "r") as f:
                    data = json.load(f)
                    self.processed_packages = data.get("processed_packages", {})
                    print(
                        f"📂 Loaded previous state: {len(self.processed_packages)} packages already processed"
                    )
            except (json.JSONDecodeError, KeyError):
                print("⚠️  Could not load previous state, starting fresh")
                self.processed_packages = {}

    def save_state(self):
        state = {
            "last_updated": datetime.now().isoformat(),
            "processed_packages": self.processed_packages,
        }
        try:
            with open(self.json_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"⚠️  Error saving state: {e}")

    def get_installed_packages(self) -> dict[str, str]:
        packages = {}
        try:
            for dist in importlib.metadata.distributions():
                name = dist.metadata.get("Name", "").lower().replace("-", "_")
                version_str = dist.version
                if name and version_str:
                    packages[name] = version_str
        except Exception as e:
            print(f"⚠️  Error getting installed packages: {e}")
        return packages

    def get_latest_version(self, package_name: str) -> dict | None:
        names_to_try = [package_name, package_name.replace("_", "-")]
        for name in names_to_try:
            url = f"https://pypi.org/pypi/{name}/json"
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    latest_version = data["info"]["version"]
                    download_url = None
                    urls = data.get("urls", [])
                    for url_info in urls:
                        if url_info.get("packagetype") == "sdist":
                            download_url = url_info.get("url")
                            break
                    if not download_url:
                        for url_info in urls:
                            if url_info.get("url", "").endswith((".tar.gz", ".zip")):
                                download_url = url_info.get("url")
                                break
                    if not download_url:
                        download_url = data["info"].get("home_page") or data[
                            "info"
                        ].get("project_url")
                    return {
                        "latest_version": latest_version,
                        "download_url": download_url,
                        "pypi_name": name,
                    }
            except requests.RequestException as e:
                print(f"  ⚠️  Network error for {name}: {e}")
                continue
            except (KeyError, ValueError) as e:
                print(f"  ⚠️  Error parsing data for {name}: {e}")
                continue
        return None

    def write_updates_to_file(self, updates: dict[str, dict]):
        try:
            with open(self.txt_file, "w") as f:
                f.write("Package Updates Available\n")
                f.write("=" * 50 + "\n\n")
                if not updates:
                    f.write("No packages need updating.\n")
                    return
                for pkg_name, info in sorted(updates.items()):
                    f.write(f"Package: {pkg_name}\n")
                    f.write(f"  Current version: {info['current_version']}\n")
                    f.write(f"  Latest version:  {info['latest_version']}\n")
                    f.write(f"  Download URL:    {info['download_url'] or 'N/A'}\n")
                    f.write("-" * 40 + "\n")
        except Exception as e:
            print(f"⚠️  Error writing to text file: {e}")

    def check_updates(self):
        print("🔍 Checking installed packages...")
        installed_packages = self.get_installed_packages()
        print(f"📦 Found {len(installed_packages)} installed packages")
        packages_to_check = {
            name: ver
            for name, ver in installed_packages.items()
            if name not in self.processed_packages
        }
        if not packages_to_check:
            print("✅ All packages already processed")
        else:
            print(f"🔄 Checking {len(packages_to_check)} packages for updates...")
            for i, (pkg_name, current_version) in enumerate(
                sorted(packages_to_check.items()), 1
            ):
                if self.interrupted:
                    break
                print(f"  [{i}/{len(packages_to_check)}] Checking {pkg_name}...")
                try:
                    latest_info = self.get_latest_version(pkg_name)
                    if latest_info:
                        latest_version = latest_info["latest_version"]
                        try:
                            needs_update = version.parse(
                                latest_version
                            ) > version.parse(current_version)
                        except version.InvalidVersion:
                            needs_update = latest_version != current_version
                        self.processed_packages[pkg_name] = {
                            "current_version": current_version,
                            "latest_version": latest_version,
                            "download_url": latest_info.get("download_url"),
                            "needs_update": needs_update,
                            "checked_at": datetime.now().isoformat(),
                        }
                        if needs_update:
                            print(
                                f"    ⬆️  Update available: {current_version} → {latest_version}"
                            )
                        else:
                            print(f"    ✓ Up to date ({current_version})")
                    else:
                        self.processed_packages[pkg_name] = {
                            "current_version": current_version,
                            "latest_version": None,
                            "download_url": None,
                            "needs_update": False,
                            "checked_at": datetime.now().isoformat(),
                            "error": "Package not found on PyPI",
                        }
                        print(f"    ⚠️  Not found on PyPI")
                except Exception as e:
                    print(f"    ❌ Error checking {pkg_name}: {e}")
                    self.processed_packages[pkg_name] = {
                        "current_version": current_version,
                        "latest_version": None,
                        "download_url": None,
                        "needs_update": False,
                        "checked_at": datetime.now().isoformat(),
                        "error": str(e),
                    }
                if i % 20 == 0:
                    self.save_state()
                    print(f"    💾 Progress saved")
                time.sleep(0.5)
        self.save_state()
        updatable = {
            name: info
            for name, info in self.processed_packages.items()
            if info.get("needs_update", False)
        }
        self.write_updates_to_file(updatable)
        print("\n" + "=" * 50)
        print("✅ Update check complete!")
        print(f"📊 Total packages checked: {len(self.processed_packages)}")
        print(f"⬆️  Updates available: {len(updatable)}")
        print(f"📄 Results saved to: {self.txt_file}")
        print(f"💾 State saved to: {self.json_file}")
        if updatable:
            print("\n📋 Packages with updates:")
            for pkg, info in sorted(updatable.items()):
                print(
                    f"  • {pkg}: {info['current_version']} → {info['latest_version']}"
                )


def main():
    checker = PackageUpdateChecker()
    checker.check_updates()


if __name__ == "__main__":
    main()
