#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path


def parse_wheel_url(url: str) -> tuple[str, str, tuple[int, ...], str] | None:
    android_pattern = r"/([^/]+)-(\d+\.\d+\.\d+)-py3-none-android_24_([^/]+)\.whl"
    linux_pattern = r"/([^/]+)-(\d+\.\d+\.\d+(?:\.\d+)?)-cp\d+-cp\d+-linux_([^/]+)\.whl"
    match = re.search(android_pattern, url)
    if match:
        package = match.group(1)
        version = tuple(map(int, match.group(2).split(".")))
        arch = match.group(3)
        return package, "android", version, arch, url
    match = re.search(linux_pattern, url)
    if match:
        package = match.group(1)
        version = tuple(map(int, match.group(2).split(".")))
        arch = match.group(3)
        py_match = re.search(r"python3\.(\d+)", url)
        python_version = py_match.group(1) if py_match else "unknown"
        return package, python_version, version, arch, url
    return None


def is_armv7_arch(arch: str) -> bool:
    armv7_patterns = ["armeabi_v7a", "armv7l", "linux_arm", "arm"]
    return any(pattern in arch.lower() for pattern in armv7_patterns)


def filter_latest_for_armv7(urls_file=None):
    urls = []
    if urls_file and Path(urls_file).exists():
        with open(urls_file) as f:
            urls = [line.strip() for line in f if line.strip()]
    elif len(sys.argv) > 1:
        if Path(sys.argv[1]).exists():
            with open(sys.argv[1]) as f:
                urls = [line.strip() for line in f if line.strip()]
        else:
            urls = sys.argv[1:]
    else:
        urls = [line.strip() for line in sys.stdin if line.strip()]
    packages: dict[tuple[str, str], dict] = defaultdict(dict)
    for url in urls:
        parsed = parse_wheel_url(url)
        if parsed:
            package, py_version, version, arch, url = parsed
            if is_armv7_arch(arch):
                key = package, py_version
                if arch not in packages[key] or version > packages[key][arch][0]:
                    packages[key][arch] = version, url
    print("-" * 40)
    print("LATEST ARMv7 (armeabi_v7a/armv7l/linux_arm) WHEELS")
    print("-" * 40)
    results = []
    for (package, py_version), arches in sorted(packages.items()):
        for arch, (version, url) in arches.items():
            version_str = ".".join(map(str, version))
            print(f"\n📦 {package} (Python {py_version})")
            print(f"   Arch: {arch}")
            print(f"   Version: {version_str}")
            print(f"   URL: {url}")
            results.append(
                {
                    "package": package,
                    "python_version": py_version,
                    "arch": arch,
                    "version": version_str,
                    "url": url,
                }
            )
    print("\n" + "=" * 40)
    print(f"SUMMARY: Found {len(results)} ARMv7 wheel(s)")
    print("-" * 40)
    for result in results:
        print(
            f"{result['package']}=={result['version']} (Python {result['python_version']})"
        )
    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Find latest ARMv7 wheels from URL list",
        epilog="Example: python3 filter_armv7.py urls.txt",
    )
    parser.add_argument(
        "input", nargs="?", default=None, help="Input file with URLs (one per line)"
    )
    parser.add_argument(
        "--output", "-o", help="Output file to save URLs (one per line)"
    )
    parser.add_argument(
        "--download", action="store_true", help="Generate download script"
    )
    args = parser.parse_args()
    results = filter_latest_for_armv7(args.input)
    if args.output:
        with open(args.output, "w") as f:
            f.writelines(f"{result['url']}\n" for result in results)
        print(f"\n✓ URLs saved to {args.output}")
    if args.download:
        script = "#!/bin/bash\n\n"
        for result in results:
            filename = result["url"].split("/")[-1]
            script += f"echo 'Downloading {filename}...'\n"
            script += f"wget {result['url']}\n\n"
        with open("download_armv7.sh", "w") as f:
            f.write(script)
        print("\n✓ Download script created: download_armv7.sh")
        print("  Run: chmod +x download_armv7.sh && ./download_armv7.sh")


if __name__ == "__main__":
    raise SystemExit(main())
