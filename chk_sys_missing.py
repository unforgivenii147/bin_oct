#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from multiprocessing import Pool, cpu_count
from pathlib import Path


def get_installed_packages() -> list[str]:
    try:
        result = subprocess.run(
            ["dpkg", "-l"], capture_output=True, text=True, check=True
        )
        packages = []
        for line in result.stdout.split("\n"):
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "ii":
                packages.append(parts[1])
        return packages
    except subprocess.CalledProcessError:
        return []


def get_package_files(pkg_name: str) -> list[Path]:
    try:
        result = subprocess.run(
            ["dpkg", "-L", pkg_name], capture_output=True, text=True, check=True
        )
        return [Path(f) for f in result.stdout.strip().split("\n") if f]
    except subprocess.CalledProcessError:
        return []


def is_ignored_path(path: Path) -> bool:
    ignore_dirs = {"share/man", "share/info", "share/doc"}
    parts = path.parts
    for i in range(len(parts) - 1):
        if (f"{parts[i]}/share" == "share" or parts[i] == "share") and i + 1 < len(
            parts
        ):
            subdir = parts[i + 1]
            if subdir in {"man", "info", "doc"}:
                return True
    path_str = str(path)
    return any(
        f"/{ignore}/" in path_str or path_str.endswith(f"/{ignore}")
        for ignore in ignore_dirs
    )


def check_package(pkg_name: str) -> dict:
    files = get_package_files(pkg_name)
    missing = []
    checked = 0
    for path in files:
        if is_ignored_path(path):
            continue
        checked += 1
        if not path.exists():
            missing.append(str(path))
    return {
        "package": pkg_name,
        "total_checked": checked,
        "missing_count": len(missing),
        "missing_files": missing,
    }


def main():
    packages = get_installed_packages()
    print(f"Found {len(packages)} installed packages")
    with Pool(cpu_count()) as pool:
        results = pool.map(check_package, packages)
    report = {
        "timestamp": datetime.now().isoformat(),
        "total_packages": len(packages),
        "summary": {
            "packages_with_missing": sum(1 for r in results if r["missing_count"] > 0),
            "total_missing_files": sum(r["missing_count"] for r in results),
        },
        "packages": [r for r in results if r["missing_count"] > 0],
    }
    report_path = Path.home() / "pkg_audit_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport: {report['summary']}")
    print(f"Saved to: {report_path}")


if __name__ == "__main__":
    raise SystemExit(main())
