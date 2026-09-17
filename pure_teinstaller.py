#!/data/data/com.termux/files/home/.local/bin/python
import multiprocessing as mp
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


def is_on_pypi(pkg_name: str) -> bool:
    """Checks PyPI JSON API to see if package exists."""
    url = f"https://pypi.org/pypi/{pkg_name}/json"
    req = urllib.request.Request(url, headers={"User-Agent": "Termux-Installer/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status == 200
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return False


def install_and_verify(pkg_name: str) -> tuple[str, bool]:
    """Re-installs package via pip if present on PyPI."""
    if not is_on_pypi(pkg_name):
        print(f"[SKIP] '{pkg_name}' not found on PyPI.")
        return pkg_name, False

    print(f"[INSTALLING] {pkg_name}...")
    cmd = ["pip", "install", "--force-reinstall", "--no-deps", pkg_name]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if result.returncode == 0:
        print(f"[SUCCESS] Re-installed {pkg_name}")
        return pkg_name, True
    else:
        print(f"[FAIL] Could not reinstall {pkg_name}")
        return pkg_name, False


def batch_generator(items: list[str], batch_size: int = 8):
    """Yields successive batches of items."""
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


def main():
    pure_file = Path("pure.txt")
    if not pure_file.exists():
        print("pure.txt not found.")
        return

    # Read and split lines, keeping non-empty packages
    packages = [
        p.strip()
        for p in pure_file.read_text(encoding="utf-8").splitlines()
        if p.strip()
    ]
    if not packages:
        print("pure.txt is empty.")
        return

    remaining_packages = set(packages)

    with mp.Pool(processes=8) as pool:
        # Process in batches of 8
        for batch in batch_generator(packages, batch_size=8):
            # Pass batch to imap_unordered
            results = pool.imap_unordered(install_and_verify, batch)

            for pkg_name, success in results:
                if success:
                    remaining_packages.discard(pkg_name)
                    # Update pure.txt in-place upon success
                    updated_content = "\n".join(sorted(remaining_packages))
                    pure_file.write_text(
                        updated_content + ("\n" if updated_content else ""),
                        encoding="utf-8",
                    )

    print(f"Done! Remaining in pure.txt: {len(remaining_packages)}")


if __name__ == "__main__":
    main()
