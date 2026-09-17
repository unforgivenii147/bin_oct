#!/data/data/com.termux/files/home/.local/bin/python
"""
Auto-build .whl files from extracted PyPI .tar.gz packages in the current directory.
Each subdirectory containing a setup.py or pyproject.toml is treated as a package.
"""

import subprocess
import sys
from multiprocessing import Pool
from pathlib import Path

NUM_WORKERS = 8
CURRENT_DIR = Path.cwd()
OUTPUT_DIR = CURRENT_DIR / "wheels"


def is_package_dir(path: Path) -> bool:
    """Check if a directory looks like a Python package source tree."""
    if not path.is_dir():
        return False
    return (
        (path / "setup.py").exists()
        or (path / "pyproject.toml").exists()
        or (path / "setup.cfg").exists()
    )


def build_wheel(pkg_dir: Path) -> tuple[str, bool, str]:
    """
    Build a wheel for a single package directory.
    Returns (package_name, success, message).
    """
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--outdir",
                str(OUTPUT_DIR),
                str(pkg_dir),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return (pkg_dir.name, True, "OK")
        else:
            return (pkg_dir.name, False, result.stderr.strip()[-500:])
    except Exception as e:
        return (pkg_dir.name, False, f"Exception: {e}")


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Discover package dirs in current dir
    pkg_dirs = sorted(
        p for p in CURRENT_DIR.iterdir() if is_package_dir(p) and p != OUTPUT_DIR
    )

    if not pkg_dirs:
        print("No package directories found in", CURRENT_DIR)
        return

    print(f"Found {len(pkg_dirs)} package(s):")
    for p in pkg_dirs:
        print("  -", p.name)
    print(f"\nBuilding wheels into: {OUTPUT_DIR}")
    print(f"Using {NUM_WORKERS} workers\n")

    # Use multiprocessing with fixed 8 workers and apply_async
    results = []
    with Pool(processes=NUM_WORKERS) as pool:
        async_results = [
            (pkg_dir, pool.apply_async(build_wheel, (pkg_dir,))) for pkg_dir in pkg_dirs
        ]

        for pkg_dir, ar in async_results:
            name, ok, msg = ar.get()
            status = "✓" if ok else "✗"
            print(f"[{status}] {name}: {msg if not ok else 'built'}")
            results.append((name, ok))

    # Summary
    success = sum(1 for _, ok in results if ok)
    failed = len(results) - success
    print(f"\nDone. Success: {success}, Failed: {failed}")


if __name__ == "__main__":
    main()
