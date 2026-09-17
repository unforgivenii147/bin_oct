#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def should_ignore(path):
    parts = Path(path).parts
    return any(
        len(parts) > i + 1 and parts[i : i + 2][1] in {"man", "info", "doc", "LICENSES"}
        for i in range(len(parts) - 1)
        if parts[i] == "share"
    )


def check_package_files(pkg_name):
    try:
        result = subprocess.run(
            ["dpkg", "-L", pkg_name],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return pkg_name, None
        missing = []
        for path in result.stdout.strip().split("\n"):
            if not path or should_ignore(path):
                continue
            p = Path(path)
            if p.is_dir():
                continue
            if not p.exists():
                missing.append(path)
        return pkg_name, missing if missing else None
    except (subprocess.TimeoutExpired, Exception):
        return pkg_name, None


def main():
    output_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("missing_files.json")
    result = subprocess.run(["dpkg", "-l"], capture_output=True, text=True, check=False)
    packages = [
        line.split()[1] for line in result.stdout.split("\n") if line.startswith("ii")
    ]
    print(f"Scanning {len(packages)} packages...")
    results = {}
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as executor:
        futures = {executor.submit(check_package_files, pkg): pkg for pkg in packages}
        for i, future in enumerate(as_completed(futures), 1):
            pkg, missing = future.result()
            if missing:
                results[pkg] = missing
            if i % 10 == 0:
                print(f"  {i}/{len(packages)}")
    try:
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)
        with open("missing.txt", "w") as f:
            f.write("\n".join(results.keys()))
        print(f"\n✓ {len(results)} packages with missing files → {output_file}")
        print(f"  Total missing: {sum(len(f) for f in results.values())}")
    except OSError as e:
        print(f"Error writing output: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    import os

    raise SystemExit(main())
