#!/data/data/com.termux/files/home/.local/bin/python
import argparse
import re
import sys
import time
from io import BytesIO
from pathlib import Path

import pycurl
from bs4 import BeautifulSoup
from dh import cprint

# Mirror configurations
MIRRORS = {
    "runflare": "https://mirror-pypi.runflare.com",
    "pypi": "https://pypi.org/simple",
    "tsinghua": "https://pypi.tuna.tsinghua.edu.cn/simple",
}
DEFAULT_MIRROR = "runflare"

TIMEOUT = 30
DOWNLOAD_DIR = Path.cwd()
MAX_RETRIES = 3
RETRY_DELAY = 2

ARCH_TAGS = [
    "win32",
    "win_amd64",
    "win_arm64",
    "win32",
    "windows",
    "manylinux",
    "musllinux",
    "linux_i686",
    "linux_x86_64",
    "linux_armv7l",
    "linux_aarch64",
    "linux_armv6l",
    "linux_armv8l",
    "macosx",
    "darwin",
    "x86_64",
    "amd64",
    "i686",
    "i386",
    "aarch64",
    "armv7l",
    "armv6l",
    "armv8l",
    "ppc64",
    "ppc64le",
    "s390x",
    "riscv64",
    "cp36",
    "cp37",
    "cp38",
    "cp39",
    "cp310",
    "cp311",
    "cp312",
    "cp313",
    "cp27",
    "cp35",
    "pp27",
    "pp36",
    "pp37",
    "pp38",
    "pp39",
    "pypy",
    "jython",
    "32",
    "64",
]

WHEEL_PLATFORM_RE = re.compile(
    r"-(cp\d+|pp\d+|py\d+)"
    r"(-(cp\d+|pp\d+|py\d+))?"
    r"-(manylinux|musllinux|win|macosx|linux|darwin)",
    re.IGNORECASE,
)


def is_windows_url(url: str) -> bool:
    """Check if URL is a Windows-tagged package."""
    lower = url.lower()
    return (
        "win32" in lower
        or "win_amd64" in lower
        or "win_arm64" in lower
        or "-win-" in lower
    )


def has_arch_tag(url: str) -> bool:
    """Check if URL has any architecture/platform specific tag."""
    lower = url.lower()
    if WHEEL_PLATFORM_RE.search(lower):
        return True
    for tag in [
        "manylinux",
        "musllinux",
        "macosx",
        "darwin",
        "x86_64",
        "amd64",
        "i686",
        "aarch64",
        "armv7l",
        "armv6l",
        "armv8l",
        "ppc64",
        "s390x",
        "riscv64",
    ]:
        if tag in lower:
            return True
    return False


def is_sdist(url: str) -> bool:
    """Check if URL points to a source distribution (.tar.gz)."""
    return url.lower().endswith(".tar.gz")


def is_pure_wheel(url: str) -> bool:
    """Check if URL is a pure Python wheel (py3-none-any)."""
    lower = url.lower()
    if not lower.endswith(".whl"):
        return False
    return "py3-none-any" in lower or "py2.py3-none-any" in lower


def select_best_url(links: list, pkg_name: str) -> tuple[str, str, str] | None:
    """
    Select best download URL from links.
    Returns (url, filename, status) where status is:
      - "download" : should be downloaded
      - "skip"     : has arch tag, should be skipped but URL reported
      - "error"    : no suitable file found
    """
    sdist_candidates = []
    pure_wheel_candidates = []
    arch_skipped = []

    for link in links:
        href = link.get("href", "").strip()
        if not href:
            continue
        url = href.split("#")[0]
        filename = link.get_text().strip() or url.split("/")[-1]

        if is_windows_url(url):
            continue

        if has_arch_tag(url):
            arch_skipped.append((url, filename))
            continue

        if is_sdist(url):
            sdist_candidates.append((url, filename))
        elif is_pure_wheel(url):
            pure_wheel_candidates.append((url, filename))

    if sdist_candidates:
        url, filename = sdist_candidates[-1]
        return (url, filename, "download")

    if pure_wheel_candidates:
        url, filename = pure_wheel_candidates[-1]
        return (url, filename, "download")

    if arch_skipped:
        url, filename = arch_skipped[-1]
        return (url, filename, "skip")

    return None


def find_existing_package(pkg_name: str) -> bool:
    """Check if any file for this package already exists in the download dir."""
    normalized = pkg_name.lower().replace("-", "_").replace(".", "_")
    pattern = re.compile(
        r"^" + re.escape(normalized) + r"[-_.]v?\d",
        re.IGNORECASE,
    )

    for f in DOWNLOAD_DIR.iterdir():
        if not f.is_file() or f.stat().st_size == 0:
            continue
        fname = f.name.lower().replace("-", "_")
        if pattern.match(fname):
            return True
    return False


def fetch_package_page(pkg_name: str, mirror_base: str, is_simple_index: bool) -> str:
    """
    Fetch the package page from the given mirror.

    - For 'simple index' style mirrors (PyPI, Tsinghua), the URL is
      {base}/{name}/  and the page contains direct links to files.
    - For the runflare mirror, the URL is {base}/{name} (no trailing slash).
    """
    if is_simple_index:
        url = f"{mirror_base.rstrip('/')}/{pkg_name}/"
    else:
        url = f"{mirror_base.rstrip('/')}/{pkg_name}"

    buffer = BytesIO()
    curl = pycurl.Curl()
    curl.setopt(curl.URL, url)
    curl.setopt(curl.WRITEDATA, buffer)
    curl.setopt(curl.FOLLOWLOCATION, 1)
    curl.setopt(curl.TIMEOUT, TIMEOUT)
    curl.setopt(
        curl.USERAGENT,
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    curl.setopt(curl.ACCEPT_ENCODING, "gzip, deflate")
    curl.setopt(
        curl.HTTPHEADER,
        [
            "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language: en-US,en;q=0.5",
        ],
    )
    try:
        curl.perform()
        response_code = curl.getinfo(curl.RESPONSE_CODE)
        if response_code != 200:
            if response_code == 402:
                print(
                    "  HTTP 402: Payment Required - The mirror might require authentication"
                )
            elif response_code == 403:
                print("  HTTP 403: Forbidden - Access denied")
            elif response_code == 404:
                print(f"  Package '{pkg_name}' not found on mirror")
            elif response_code == 429:
                print("  HTTP 429: Too Many Requests - Rate limited")
            return ""
        return buffer.getvalue().decode("utf-8", errors="replace")
    except Exception:
        return ""
    finally:
        curl.close()


def extract_latest_download_url(
    html: str, pkg_name: str
) -> tuple[str, str, str] | None:
    try:
        soup = BeautifulSoup(html, "html.parser")
        all_links = soup.find_all("a", href=True)
        if not all_links:
            return None
        return select_best_url(all_links, pkg_name)
    except Exception:
        return None


def download_file_with_retry(
    url: str, filename: str, max_retries: int = MAX_RETRIES
) -> bool:
    for attempt in range(max_retries):
        if attempt > 0:
            time.sleep(RETRY_DELAY * attempt)
        if download_file(url, filename):
            return True
    return False


def download_file(url: str, filename: str, referer: str = "") -> bool:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DOWNLOAD_DIR / filename
    if output_path.exists() and output_path.stat().st_size > 0:
        return True
    print(f"  Downloading: {filename}")
    with open(output_path, "wb") as f:
        curl = pycurl.Curl()
        curl.setopt(curl.URL, url)
        curl.setopt(curl.WRITEDATA, f)
        curl.setopt(curl.FOLLOWLOCATION, 1)
        curl.setopt(curl.TIMEOUT, 120)
        curl.setopt(
            curl.USERAGENT,
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        curl.setopt(curl.ACCEPT_ENCODING, "gzip, deflate")
        headers = [
            "Accept: */*",
            "Accept-Language: en-US,en;q=0.5",
        ]
        if referer:
            headers.append(f"Referer: {referer}")
        curl.setopt(curl.HTTPHEADER, headers)
        curl.setopt(curl.NOPROGRESS, 0)

        def progress_callback(download_t, download_d, upload_t, upload_d):
            if download_t > 0:
                percent = (download_d * 40) / download_t
                if int(percent) % 10 == 0:
                    cprint(
                        f"  Progress: {percent:.1f}% ({download_d:,}/{download_t:,} bytes)",
                        end="\r",
                    )
            else:
                cprint(f"  Downloaded: {download_d:,} bytes", end="\r")
            return 0

        curl.setopt(curl.XFERINFOFUNCTION, progress_callback)
        try:
            curl.perform()
            response_code = curl.getinfo(curl.RESPONSE_CODE)
            if response_code == 200:
                print()
                return True
            else:
                if response_code == 402:
                    print(
                        "  HTTP 402: Payment Required - The mirror might require authentication or has usage limits"
                    )
                elif response_code == 403:
                    print("  HTTP 403: Forbidden - Access denied")
                elif response_code == 404:
                    print("  HTTP 404: File not found on mirror")
                elif response_code == 429:
                    print(
                        "  HTTP 429: Too Many Requests - Rate limited, try again later"
                    )
                if output_path.exists():
                    output_path.unlink()
                return False
        except Exception:
            return False
        finally:
            curl.close()


def process_package(
    pkg_name: str, mirror_base: str, is_simple_index: bool
) -> tuple[bool, bool]:
    """
    Returns (success, skipped).
    - success: True if downloaded successfully OR skipped (counts as OK)
    - skipped: True if file had arch tag and was not downloaded
    """
    html = fetch_package_page(pkg_name, mirror_base, is_simple_index)
    if not html:
        return (False, False)
    download_info = extract_latest_download_url(html, pkg_name)
    if not download_info:
        return (False, False)

    url, filename, status = download_info

    if status == "skip":
        return (True, True)

    print(f"Download URL: {url}")
    ok = download_file_with_retry(url, filename)
    return (ok, False)


def load_packages_from_file(file_path: str) -> list[str]:
    """
    Load package names from a file (one per line).
    - Ignores empty lines and comments (lines starting with #).
    - Strips inline comments (everything after #).
    - Strips version specifiers, keeping only the package name.
    """
    path = Path(file_path)
    if not path.is_file():
        print(f"Error: file not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    packages = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.split("#", 1)[0].strip()
                if not line:
                    continue
                m = re.match(r"^([A-Za-z0-9_.\-]+)", line)
                if m:
                    packages.append(m.group(1))
    except OSError as e:
        print(f"Error reading file {file_path}: {e}", file=sys.stderr)
        sys.exit(1)

    return packages


def main():
    parser = argparse.ArgumentParser(
        prog="pypi-mirror-dl",
        description="Download packages from a PyPI mirror (source distributions "
        "and pure-Python wheels preferred; arch-specific wheels skipped).",
        epilog="Mirror selection: default is runflare. Use -p for official PyPI, "
        "-c for Tsinghua (China). -p and -c are mutually exclusive.",
    )
    parser.add_argument(
        "packages",
        nargs="*",
        help="Package name(s) to download.",
    )
    parser.add_argument(
        "-f",
        "--file",
        dest="file",
        metavar="FILE",
        help="Read package names from FILE (one per line; blank lines and "
        "'#' comments are ignored).",
    )
    parser.add_argument(
        "-d",
        "--dir",
        dest="directory",
        metavar="DIR",
        help="Download directory (default: current directory).",
    )

    mirror_group = parser.add_mutually_exclusive_group()
    mirror_group.add_argument(
        "-p",
        "--pypi",
        action="store_true",
        help="Download from official PyPI (https://pypi.org/simple).",
    )
    mirror_group.add_argument(
        "-c",
        "--china",
        action="store_true",
        help="Download from Tsinghua PyPI mirror (China).",
    )
    mirror_group.add_argument(
        "-m",
        "--mirror",
        choices=list(MIRRORS.keys()),
        help="Explicitly choose a mirror by name (default: runflare).",
    )

    args = parser.parse_args()

    # Resolve mirror
    if args.pypi:
        mirror_key = "pypi"
    elif args.china:
        mirror_key = "tsinghua"
    elif args.mirror:
        mirror_key = args.mirror
    else:
        mirror_key = DEFAULT_MIRROR

    mirror_base = MIRRORS[mirror_key]
    # PyPI and Tsinghua serve the PEP 503 "simple index" (with trailing slash)
    is_simple_index = mirror_key in ("pypi", "tsinghua")

    # Optionally change download dir
    global DOWNLOAD_DIR
    if args.directory:
        DOWNLOAD_DIR = Path(args.directory).expanduser().resolve()
        if not DOWNLOAD_DIR.is_dir():
            print(
                f"Error: download directory does not exist: {DOWNLOAD_DIR}",
                file=sys.stderr,
            )
            sys.exit(1)

    # Collect packages from CLI args and file
    packages = list(args.packages)
    if args.file:
        file_pkgs = load_packages_from_file(args.file)
        print(f"Loaded {len(file_pkgs)} package(s) from {args.file}")
        packages.extend(file_pkgs)

    if not packages:
        parser.print_help()
        sys.exit(1)

    # Deduplicate while preserving order
    seen = set()
    unique_packages = []
    for p in packages:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            unique_packages.append(p)
    packages = unique_packages

    print(f"Mirror: {mirror_key} ({mirror_base})")
    print(f"Download dir: {DOWNLOAD_DIR}")
    print(f"Processing {len(packages)} package(s)...\n")

    start_time = time.time()
    successful = []
    failed = []
    skipped = []
    already_exists = []

    for pkg_name in packages:
        print(f"[{pkg_name}]")
        try:
            if find_existing_package(pkg_name):
                print(f"  Already exists, skipping")
                already_exists.append(pkg_name)
                continue
            ok, was_skipped = process_package(pkg_name, mirror_base, is_simple_index)
            if was_skipped:
                skipped.append(pkg_name)
            elif ok:
                successful.append(pkg_name)
            else:
                failed.append(pkg_name)
        except Exception as e:
            print(f"  Error: {e}")
            failed.append(pkg_name)

    elapsed = time.time() - start_time

    if successful:
        print(f"\nSuccessfully downloaded:")
        for pkg in successful:
            print(f"  ✓ {pkg}")
    if already_exists:
        print(f"\nAlready present:")
        for pkg in already_exists:
            print(f"  • {pkg}")
    if skipped:
        print(f"\nSkipped (arch-specific, no pure source/wheel available):")
        for pkg in skipped:
            print(f"  ⚠ {pkg}")
    if failed:
        print(f"\nFailed to download:")
        for pkg in failed:
            print(f"  ✗ {pkg}")

    print(
        f"\nDone in {elapsed:.1f}s — "
        f"{len(successful)} downloaded, "
        f"{len(already_exists)} already present, "
        f"{len(skipped)} skipped, "
        f"{len(failed)} failed"
    )

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
