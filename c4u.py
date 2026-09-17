#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import asdict, dataclass
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Any

from dh import get_installed_packages


def setup_logging(verbose: bool = True) -> logging.Logger:
    logger = logging.getLogger("pkg_updater")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler = logging.FileHandler("pkg_updater.log")
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger


logger = setup_logging(verbose=True)


@dataclass
class PackageInfo:
    pkgname: str
    installed_version: str
    latest_version: str | None = None
    upgradable: bool = False
    checked_at: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PackageInfo:
        return cls(**data)


class PackageStateManager:
    def __init__(self, state_file: Path = Path("pkgs_state.json")) -> None:
        self.state_file = state_file
        self.state: dict[str, PackageInfo] = {}
        self._load_state()

    def _load_state(self) -> None:
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    raw_state = json.load(f)
                self.state = {
                    name: PackageInfo.from_dict(data)
                    for name, data in raw_state.items()
                }
                print(
                    f"✓ Resumed state: {len(self.state)} packages loaded from {self.state_file}"
                )
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"✗ Failed to load state: {e}. Starting fresh.")
                self.state = {}
        else:
            print("📁 No existing state file. Starting fresh.")

    def save_state(self) -> None:
        state_dict = {name: pkg.to_dict() for name, pkg in self.state.items()}
        with open(self.state_file, "w") as f:
            json.dump(state_dict, f, indent=2)
        logger.debug(f"💾 State saved: {self.state_file}")

    def update_package(self, pkg_info: PackageInfo) -> None:
        self.state[pkg_info.pkgname] = pkg_info

    def get_pending_packages(self, all_packages: list[str]) -> list[str]:
        return [p for p in all_packages if p not in self.state]

    def get_upgradable_packages(self) -> list[PackageInfo]:
        return [pkg for pkg in self.state.values() if pkg.upgradable]


def query_pypi(
    package_name: str, installed_version: str, retries: int = 2
) -> PackageInfo:
    import requests

    url = f"https://pypi.org/pypi/{package_name}/json"
    pkg_info = PackageInfo(
        pkgname=package_name,
        installed_version=installed_version,
        checked_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            latest_version = data["info"]["version"]
            pkg_info.latest_version = latest_version
            pkg_info.upgradable = _is_upgradable(installed_version, latest_version)
            status = "🔄 upgradable" if pkg_info.upgradable else "✓ up-to-date"
            logger.debug(
                f"{status:20} | {package_name:30} {installed_version} → {latest_version}"
            )
            return pkg_info
        except requests.exceptions.Timeout:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            pkg_info.error = "Timeout"
            logger.warning(f"⏱ Timeout: {package_name}")
            return pkg_info
        except requests.exceptions.HTTPError:
            if response.status_code == 404:
                pkg_info.error = "Not found on PyPI"
                logger.warning(f"❌ Not found: {package_name}")
            else:
                pkg_info.error = f"HTTP {response.status_code}"
                logger.warning(f"⚠ HTTP error: {package_name} ({response.status_code})")
            return pkg_info
        except Exception as e:
            pkg_info.error = str(e)
            logger.warning(f"⚠ Error: {package_name} - {e}")
            return pkg_info
    return pkg_info


def _is_upgradable(installed: str, latest: str) -> bool:
    try:
        from packaging import version

        return version.parse(latest) > version.parse(installed)
    except Exception:
        try:
            installed_parts = [int(x) for x in installed.split(".")[:3]]
            latest_parts = [int(x) for x in latest.split(".")[:3]]
            return tuple(latest_parts) > tuple(installed_parts)
        except (ValueError, IndexError):
            return False


def main() -> None:
    print("=" * 40)
    print("🚀 PyPI Package Update Checker (Multiprocessing Enabled)")
    print("=" * 40)
    state_manager = PackageStateManager()
    installed = get_installed_packages()
    all_package_names = [name for name, _ in installed]
    pending = state_manager.get_pending_packages(all_package_names)
    already_checked = len(all_package_names) - len(pending)
    print(f"📊 Status: {already_checked} checked, {len(pending)} pending")
    if not pending:
        print("✓ All packages already checked. Skipping PyPI queries.")
    else:
        pending_packages = [
            (name, next(v for n, v in installed if n == name)) for name in pending
        ]
        num_workers = min(cpu_count(), 8)
        print(f"🔄 Spawning {num_workers} workers to query PyPI...")
        with Pool(processes=num_workers) as pool:
            results = pool.starmap(
                query_pypi,
                pending_packages,
                chunksize=max(1, len(pending_packages) // num_workers),
            )
        for pkg_info in results:
            state_manager.update_package(pkg_info)
        print(f"✓ Completed {len(results)} PyPI queries")
    state_manager.save_state()
    upgradable = state_manager.get_upgradable_packages()
    if upgradable:
        req_file = Path("requirements_upgradable.txt")
        with open(req_file, "w") as f:
            f.writelines(
                f"{pkg.pkgname}=={pkg.latest_version}\n"
                for pkg in sorted(upgradable, key=lambda x: x.pkgname)
            )
        print(f"📝 {len(upgradable)} upgradable packages saved to {req_file}")
    else:
        print("✓ All packages are up-to-date!")
    print("=" * 40)
    print("📈 SUMMARY")
    print(f"   Total packages: {len(state_manager.state)}")
    print(f"   Upgradable: {len(upgradable)}")
    print(f"   Up-to-date: {len(state_manager.state) - len(upgradable)}")
    print("=" * 40)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n⏹ Interrupted by user. State saved.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"✗ Fatal error: {e}", exc_info=True)
        sys.exit(1)
