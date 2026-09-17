#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import concurrent.futures
import json
import pathlib
import urllib.error
import urllib.request


def get_pypi_json(package: str, timeout: int = 10) -> dict | None:
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        print(f"  ❌ Error fetching {package}: {e}")
        return None


def find_wheel_url(
    package_data: dict, python_version: str = "3.12"
) -> tuple[str, int] | None:
    releases = package_data.get("releases", {})
    if not releases:
        return None
    latest_version = max(releases.keys())
    files = releases[latest_version]
    wheels = []
    for file in files:
        if not file.get("packagetype") == "bdist_wheel":
            continue
        filename = file["filename"].lower()
        pv = file.get("python_version", "").lower()
        score = 0
        if f"cp{python_version.replace('.', '')}" in filename:
            score += 100
        if pv == f"=={python_version}":
            score += 100
        if pv.startswith(f">={python_version}"):
            score += 90
        if "py3" in filename and "none" in filename:
            score += 80
        if "abi3" in filename:
            score += 70
        if pv.startswith(">=3."):
            score += 60
        if score > 0:
            wheels.append((score, file))
    if not wheels:
        return None
    _, best_wheel = max(wheels, key=lambda x: x[0])
    return best_wheel["url"], best_wheel["size"]


def download_file(
    url: str, destination: pathlib.Path, expected_size: int, chunk_size: int = 8192
) -> tuple[bool, str]:
    print(
        f"  📥 Downloading {destination.name} ({expected_size / 1024 / 1024:.2f} MB)..."
    )
    try:
        with urllib.request.urlopen(url) as response:
            total_size = int(response.headers.get("content-length", expected_size))
            downloaded = 0
            with open(destination, "wb") as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    percent = downloaded / total_size * 40
                    print(
                        f"    ⬇ {downloaded / 1024 / 1024:.2f} MB / {total_size / 1024 / 1024:.2f} MB ({percent:.1f}%)",
                        end="\r",
                    )
            print(
                f"    ✅ Downloaded {destination.name} ({downloaded / 1024 / 1024:.2f} MB)"
            )
            return True, ""
    except Exception as e:
        return False, f"Failed: {e!s}"


def download_package(
    package: str, wheels_dir: pathlib.Path, python_version: str = "3.12"
) -> tuple[str, bool, str]:
    print(f"🔍 Fetching info for: {package}")
    package_data = get_pypi_json(package)
    if not package_data:
        return package, False, "Failed to fetch package info from PyPI"
    wheel_info = find_wheel_url(package_data, python_version)
    if not wheel_info:
        return (
            package,
            False,
            "No compatible wheel found for Python " + python_version,
        )
    url, size = wheel_info
    filename = url.split("/")[-1]
    destination = wheels_dir / filename
    print(f"  📊 Package: {package}")
    print(f"  🔗 URL: {url}")
    print(f"  💾 Size: {size / 1024 / 1024:.2f} MB")
    success, message = download_file(url, destination, size)
    return package, success, message


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Download Python packages from PyPI as wheels"
    )
    parser.add_argument("packages", nargs="+", help="Package name(s) to download")
    parser.add_argument(
        "--python", default="3.12", help="Python version (default: 3.12)"
    )
    parser.add_argument(
        "--workers", type=int, default=4, help="Number of download workers (default: 4)"
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("wheels"),
        help="Output directory (default: wheels)",
    )
    args = parser.parse_args()
    wheels_dir = args.output.resolve()
    wheels_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Saving wheels to: {wheels_dir}\n")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(download_package, pkg, wheels_dir, args.python): pkg
            for pkg in args.packages
        }
        success_count = 0
        for future in concurrent.futures.as_completed(futures):
            package, success, message = future.result()
            if success:
                success_count += 1
            else:
                print(f"  ⚠️  {package}: {message}")
    print(
        f"\n✅ Downloaded {success_count}/{len(args.packages)} packages successfully."
    )


if __name__ == "__main__":
    raise SystemExit(main())
