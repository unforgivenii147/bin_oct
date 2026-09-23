#!/data/data/com.termux/files/home/.local/bin/python
"""Download Python packages from a PyPI mirror.

Backend
-------
All network I/O goes through ``httpx.AsyncClient`` (async, connection-pooled,
supports streaming).  Packages are processed concurrently, bounded by an
``asyncio.Semaphore``.

Strategy
--------
For each package we fetch the mirror's package page, parse out the list of
published files, and pick the "best" candidate according to this priority:

    1. Source distribution (``.tar.gz``, ``.zip``, ``.tar.bz2``, ``.tar.xz``,
       ``.tgz``) — portable across platforms.
    2. Pure-Python wheel (``py3-none-any``) — portable across platforms.
    3. Anything else is treated as an arch-specific binary and *skipped*.

Any file larger than ``MAX_FILE_SIZE`` (default 1 MiB) is skipped, both as a
pre-flight check on ``Content-Length`` and as a mid-stream safety net.

Integrity
---------
Every newly downloaded archive is validated before it's accepted:

    * ``.tar.gz`` / ``.tgz`` / ``.tar.bz2`` / ``.tar.xz`` → ``tarfile``
      (auto-detects compression); every file member's payload is drained
      so gzip/bz2/xz checksums are verified.
    * ``.zip`` / ``.whl``                                 → ``zipfile``
      (``testzip`` checks CRCs of every member).

Validation runs by default with no CLI flag.  If it fails, the partial
file is removed and the download is retried (up to ``MAX_RETRIES``).

Version pinning
---------------
Each argument / line may be either ``name`` or ``name==version`` (e.g.
``aiohttp==3.5.16``).  When a version is pinned we filter the mirror's
file list down to entries whose *normalised* filename starts with
``<normalised-name>_<normalised-version>_`` (PEP 503 separators) before
applying the usual sdist → pure-wheel → skip priority.
"""

import argparse
import asyncio
import re
import sys
import tarfile
import time
import zipfile
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from dh import cprint  # kept for parity with the original script

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MIRRORS = {
    "runflare": "https://mirror-pypi.runflare.com",
    "pypi": "https://pypi.org/simple",
    "tsinghua": "https://pypi.tuna.tsinghua.edu.cn/simple",
}
# Default mirror is now official PyPI (previously "tsinghua").
DEFAULT_MIRROR = "pypi"

# Timeouts (seconds).  ``read`` applies per chunk, so long downloads are fine.
PAGE_TIMEOUT = 30.0
DOWNLOAD_TIMEOUT = 120.0

DOWNLOAD_DIR = Path.cwd()  # Overwritten by -d / --dir
MAX_RETRIES = 2
RETRY_DELAY = 2  # Base seconds for linear back-off
DEFAULT_CONCURRENCY = 4
CHUNK_SIZE = 32768

MAX_FILE_SIZE = 1024 * 1024  # 1 MiB by default (override with --max-size)

SDIST_EXTENSIONS = (
    ".tar.gz",
    ".zip",
    ".tar.bz2",
    ".tar.xz",
    ".tgz",
)

# Extensions we know how to validate, and which validator to use.
TAR_EXTENSIONS = (".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tbz2", ".tbz")
ZIP_EXTENSIONS = (".zip", ".whl")

# Matches wheel filenames like  <name>-<pyver>-<abi>-<platform>.whl
WHEEL_PLATFORM_RE = re.compile(
    r"-(cp\d+|pp\d+|py\d+)"
    r"(-(cp\d+|pp\d+|py\d+))?"
    r"-(manylinux|musllinux|win|macosx|linux|darwin)",
    re.IGNORECASE,
)

# Substrings indicating a platform / architecture-specific artifact.
ARCH_TAGS = [
    "win32",
    "win_amd64",
    "win_arm64",
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
    "cp27",
    "cp35",
    "cp36",
    "cp37",
    "cp38",
    "cp39",
    "cp310",
    "cp311",
    "cp312",
    "cp313",
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

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Serialises multi-line output so concurrent tasks don't garble each other.
_PRINT_LOCK = asyncio.Lock()


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class FileTooLarge(Exception):
    """Raised when a remote file exceeds ``MAX_FILE_SIZE``.

    We use an exception (rather than a boolean return) so the signal
    bypasses the retry loop — retrying an oversized file is pointless.
    """

    def __init__(self, size: int):
        super().__init__(f"file is {size} bytes (limit: {MAX_FILE_SIZE})")
        self.size = size


# ---------------------------------------------------------------------------
# Package-spec parsing (pure, synchronous)
# ---------------------------------------------------------------------------


def _norm_sep(s: str) -> str:
    """Normalise PEP-503-style separators.

    ``-``, ``_``, and ``.`` all collapse to ``_`` and the result is
    lower-cased.  This lets us compare ``aiohttp-3.5.16.tar.gz`` with
    ``aiohttp_3_5_16_...`` without caring which separator the mirror used.
    """
    return re.sub(r"[-_.]+", "_", s).lower()


def parse_package_spec(spec: str) -> tuple:
    """Split ``'name'`` or ``'name==version'`` into ``(name, version|None)``.

    Only ``==`` is recognised (the common exact-pin operator).  Anything
    else — ``>=``, ``~=``, extras like ``pkg[foo]`` — is passed through
    untouched as part of the name, matching the previous behaviour.
    """
    spec = spec.strip()
    if "==" in spec:
        name, _, version = spec.partition("==")
        name, version = name.strip(), version.strip()
        return name, (version or None)
    return spec, None


# ---------------------------------------------------------------------------
# URL / filename classification (pure, synchronous)
# ---------------------------------------------------------------------------


def is_windows_url(url: str) -> bool:
    """Return True if the URL clearly refers to a Windows-only artifact."""
    lower = url.lower()
    return (
        "win32" in lower
        or "win_amd64" in lower
        or "win_arm64" in lower
        or "-win-" in lower
    )


def has_arch_tag(url: str) -> bool:
    """Return True if the URL carries any platform / architecture tag."""
    lower = url.lower()
    if WHEEL_PLATFORM_RE.search(lower):
        return True
    for tag in ARCH_TAGS:
        if tag in lower:
            return True
    return False


def is_sdist(url: str) -> bool:
    """Return True if the URL points to a source distribution archive."""
    return url.lower().endswith(SDIST_EXTENSIONS)


def is_pure_wheel(url: str) -> bool:
    """Return True if the URL points to a pure-Python wheel (py3-none-any)."""
    lower = url.lower()
    if not lower.endswith(".whl"):
        return False
    return "py3-none-any" in lower or "py2.py3-none-any" in lower


# ---------------------------------------------------------------------------
# Archive integrity validation
# ---------------------------------------------------------------------------


def _validate_tar(path: Path) -> tuple:
    """Validate a tar archive (any compression).  Returns (ok, message).

    ``tarfile`` with mode ``"r:*"`` auto-detects gzip / bz2 / xz / plain.
    We drain every member's payload so the decompressor's own checksum
    (gzip CRC32, bz2/xz CRC) is actually verified — just listing members
    wouldn't touch the compressed payload.
    """
    try:
        # ``errorlevel=2`` makes tarfile raise on any recoverable
        # corruption rather than silently producing garbage members.
        with tarfile.open(path, "r:*", errorlevel=2) as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                f = tf.extractfile(member)
                if f is None:
                    continue
                # Drain in chunks to avoid holding large members in RAM.
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
        return True, ""
    except (tarfile.TarError, EOFError, OSError) as e:
        return False, f"{type(e).__name__}: {e}"


def _validate_zip(path: Path) -> tuple:
    """Validate a zip / wheel archive.  Returns (ok, message).

    ``ZipFile.testzip()`` reads every member and verifies its CRC32,
    returning the name of the first bad member (or ``None`` if clean).
    """
    try:
        with zipfile.ZipFile(path, "r") as zf:
            bad = zf.testzip()
            if bad is not None:
                return False, f"corrupt member: {bad}"
        return True, ""
    except (zipfile.BadZipFile, EOFError, OSError) as e:
        return False, f"{type(e).__name__}: {e}"


def validate_archive(path: Path, filename: str) -> tuple:
    """Dispatch to the right validator based on filename.

    Returns ``(ok, message)``.  Unknown extensions are treated as valid
    (we can't know how to check them).
    """
    lower = filename.lower()
    if lower.endswith(TAR_EXTENSIONS):
        return _validate_tar(path)
    if lower.endswith(ZIP_EXTENSIONS):
        return _validate_zip(path)
    return True, ""


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


def select_best_url(links: list, pkg_name: str, version=None):
    """Pick the best download URL from a list of ``<a>`` tags.

    If ``version`` is supplied, only files whose normalised name begins
    with ``<normalised pkg>_<normalised version>_`` (or equals it) are
    eligible.  This is what makes ``name==version`` pinning work.

    Returns ``(url, filename, status)`` where status is one of
    ``"download"`` / ``"skip"`` / ``None``.
    """
    sdist_candidates: list = []
    pure_wheel_candidates: list = []
    arch_skipped: list = []

    if version:
        # ``aiohttp==3.5.16`` → prefix ``aiohttp_3_5_16``
        prefix = f"{_norm_sep(pkg_name)}_{_norm_sep(version)}"

        def version_match(filename: str) -> bool:
            fn = _norm_sep(filename)
            # e.g. "aiohttp_3_5_16.tar.gz"  (fn startswith prefix + "_")
            # or   "aiohttp_3_5_16"         (fn == prefix, unlikely but safe)
            return fn.startswith(prefix + "_") or fn == prefix
    else:

        def version_match(filename: str) -> bool:
            return True

    for link in links:
        href = link.get("href", "").strip()
        if not href:
            continue

        url = href.split("#")[0]  # drop ``#sha256=…``
        filename = link.get_text().strip() or url.split("/")[-1]

        # Filter out non-matching versions *before* the sdist/wheel/arch
        # classification so the priority logic only sees the target version.
        if not version_match(filename):
            continue

        if is_windows_url(url):
            continue
        if has_arch_tag(url):
            arch_skipped.append((url, filename))
            continue
        if is_sdist(url):
            sdist_candidates.append((url, filename))
            continue
        if is_pure_wheel(url):
            pure_wheel_candidates.append((url, filename))

    # Newest versions are usually last → take the tail.  SDists win.
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


# ---------------------------------------------------------------------------
# Local filesystem helpers
# ---------------------------------------------------------------------------


def find_existing_package(pkg_name: str, version=None) -> bool:
    """Return True if a non-empty file for ``pkg_name`` already exists.

    If ``version`` is given, only files matching that exact version are
    considered, so re-running with a different pin will re-download.
    """
    normalized = _norm_sep(pkg_name)

    if version:
        prefix = f"{normalized}_{_norm_sep(version)}"
        pattern = re.compile(r"^" + re.escape(prefix) + r"(?:_|$)", re.IGNORECASE)
    else:
        # Match any version: ``pkg_3``, ``pkg_v3``, ...
        pattern = re.compile(r"^" + re.escape(normalized) + r"_v?\d", re.IGNORECASE)

    for f in DOWNLOAD_DIR.iterdir():
        if not f.is_file() or f.stat().st_size == 0:
            continue
        fname = _norm_sep(f.name)
        if pattern.match(fname):
            return True
    return False


# ---------------------------------------------------------------------------
# Async network layer
# ---------------------------------------------------------------------------


async def fetch_package_page(
    client: httpx.AsyncClient,
    pkg_name: str,
    mirror_base: str,
    is_simple_index: bool,
) -> str:
    """Fetch the HTML index page for ``pkg_name``.

    Returns decoded HTML on success, ``""`` on any failure.
    """
    if is_simple_index:
        url = f"{mirror_base.rstrip('/')}/{pkg_name}/"
    else:
        url = f"{mirror_base.rstrip('/')}/{pkg_name}"

    try:
        r = await client.get(url, timeout=PAGE_TIMEOUT)
    except httpx.HTTPError as e:
        print(f"[{pkg_name}]  Network error: {e}")
        return ""

    if r.status_code != 200:
        if r.status_code == 402:
            print(f"[{pkg_name}]  HTTP 402: Payment Required")
        elif r.status_code == 403:
            print(f"[{pkg_name}]  HTTP 403: Forbidden")
        elif r.status_code == 404:
            print(f"[{pkg_name}]  Package not found on mirror")
        elif r.status_code == 429:
            print(f"[{pkg_name}]  HTTP 429: Rate limited")
        else:
            print(f"[{pkg_name}]  HTTP {r.status_code}")
        return ""

    return r.text


async def download_file(
    client: httpx.AsyncClient,
    url: str,
    filename: str,
    pkg_name: str = "",
    referer: str = "",
) -> bool:
    """Stream ``url`` into ``DOWNLOAD_DIR/filename``, then validate it.

    Raises :class:`FileTooLarge` if the file exceeds ``MAX_FILE_SIZE``,
    either from the ``Content-Length`` header (pre-flight) or from actual
    bytes received (safety net for chunked responses).

    Returns True on HTTP 200 + full download + successful integrity check.
    Returns False on any other failure (or if validation fails — the
    partial file is deleted so the retry loop can try again).
    """
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DOWNLOAD_DIR / filename

    # Already there and non-empty → nothing to do.
    if output_path.exists() and output_path.stat().st_size > 0:
        return True

    print(f"[{pkg_name}]  Downloading: {filename}")

    headers = {"Accept": "*/*", "Accept-Language": "en-US,en;q=0.5"}
    if referer:
        headers["Referer"] = referer

    try:
        async with client.stream(
            "GET", url, headers=headers, timeout=DOWNLOAD_TIMEOUT
        ) as r:
            if r.status_code != 200:
                if r.status_code == 402:
                    print(f"[{pkg_name}]  HTTP 402: Payment Required")
                elif r.status_code == 403:
                    print(f"[{pkg_name}]  HTTP 403: Forbidden")
                elif r.status_code == 404:
                    print(f"[{pkg_name}]  HTTP 404: File not found")
                elif r.status_code == 429:
                    print(f"[{pkg_name}]  HTTP 429: Rate limited")
                else:
                    print(f"[{pkg_name}]  HTTP {r.status_code}")
                return False

            # ---- Pre-flight size check -------------------------------
            # ``r.headers`` is already populated; the body hasn't been
            # consumed yet, so we can bail out with zero bytes read.
            try:
                total = int(r.headers.get("content-length", "0") or 0)
            except ValueError:
                total = 0

            if total > MAX_FILE_SIZE:
                # Raising here exits the ``async with`` cleanly — httpx
                # closes the connection without us pulling the body.
                raise FileTooLarge(total)

            # ---- Stream the body -------------------------------------
            downloaded = 0
            next_milestone = 25

            with open(output_path, "wb") as f:
                async for chunk in r.aiter_bytes(chunk_size=CHUNK_SIZE):
                    downloaded += len(chunk)

                    # Mid-stream safety net: server lied about
                    # Content-Length, or used chunked encoding with no
                    # advertised length.  Abort as soon as we exceed
                    # the cap.
                    if downloaded > MAX_FILE_SIZE:
                        raise FileTooLarge(downloaded)

                    f.write(chunk)

                    if total > 0:
                        pct = downloaded * 100 // total
                        if pct >= next_milestone:
                            async with _PRINT_LOCK:
                                cprint(
                                    f"[{pkg_name}]  Progress: {pct}% "
                                    f"({downloaded:,}/{total:,} bytes)"
                                )
                            next_milestone = (pct // 25 + 1) * 25

        # ---- Integrity check (default, no CLI toggle) -----------------
        # Runs in a worker thread so blocking disk reads / decompression
        # don't stall the event loop for other concurrent downloads.
        ok, msg = await asyncio.to_thread(validate_archive, output_path, filename)
        if not ok:
            print(f"[{pkg_name}]  Integrity check failed: {msg}")
            try:
                output_path.unlink()
            except OSError:
                pass
            return False

        return True

    except FileTooLarge:
        # Clean up any partial file, then let the signal propagate to
        # the caller so it can be tagged as "too_large".
        if output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass
        raise

    except httpx.HTTPError as e:
        print(f"[{pkg_name}]  Network error: {e}")
        if output_path.exists():
            output_path.unlink()
        return False
    except Exception as e:
        print(f"[{pkg_name}]  Unexpected error: {e}")
        if output_path.exists():
            output_path.unlink()
        return False


async def download_file_with_retry(
    client: httpx.AsyncClient,
    url: str,
    filename: str,
    pkg_name: str = "",
    max_retries: int = MAX_RETRIES,
) -> bool:
    """Linear-back-off wrapper around :func:`download_file`.

    ``FileTooLarge`` is *not* retried — it propagates straight through.
    Corrupt downloads (integrity-check failures) fall through here as a
    plain ``False`` and therefore *are* retried.
    """
    for attempt in range(max_retries):
        if attempt > 0:
            await asyncio.sleep(RETRY_DELAY * attempt)
        if await download_file(client, url, filename, pkg_name=pkg_name):
            return True
    return False


async def process_package(
    client: httpx.AsyncClient,
    spec: str,
    mirror_base: str,
    is_simple_index: bool,
    semaphore: asyncio.Semaphore,
) -> tuple:
    """Fetch, select and download one package under ``semaphore``.

    ``spec`` is either ``"name"`` or ``"name==version"``.  Returns
    ``(spec, status)`` where status ∈
    ``{"ok", "exists", "skipped", "too_large", "failed"}``.
    """
    pkg_name, version = parse_package_spec(spec)
    label = f"{pkg_name}=={version}" if version else pkg_name

    async with semaphore:
        try:
            if find_existing_package(pkg_name, version):
                print(f"[{label}]  Already exists, skipping")
                return (spec, "exists")

            html = await fetch_package_page(
                client, pkg_name, mirror_base, is_simple_index
            )
            if not html:
                return (spec, "failed")

            info = None
            try:
                soup = BeautifulSoup(html, "html.parser")
                links = soup.find_all("a", href=True)
                if links:
                    info = select_best_url(links, pkg_name, version)
            except Exception as e:
                print(f"[{label}]  Parse error: {e}")
                return (spec, "failed")

            if not info:
                if version:
                    print(f"[{label}]  Version not found on mirror")
                else:
                    print(f"[{label}]  No suitable file found on mirror")
                return (spec, "failed")

            url, filename, status = info

            if status == "skip":
                print(f"[{label}]  Skipped (arch-specific only): {filename}")
                return (spec, "skipped")

            print(f"[{label}]  URL: {url}")

            try:
                ok = await download_file_with_retry(
                    client, url, filename, pkg_name=label
                )
                return (spec, "ok" if ok else "failed")

            except FileTooLarge as e:
                # Report the actual size we saw (Content-Length or
                # bytes-received-so-far) plus the configured limit.
                size_mib = e.size / (1024 * 1024)
                cap_mib = MAX_FILE_SIZE / (1024 * 1024)
                print(
                    f"[{label}]  Skipped (size {size_mib:.2f} MiB "
                    f"> {cap_mib:.2f} MiB limit)"
                )
                return (spec, "too_large")

        except Exception as e:
            print(f"[{label}]  Error: {e}")
            return (spec, "failed")


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------


def load_packages_from_file(file_path: str) -> list:
    """Read package names / specs from a text file.

    Each line may be ``name`` or ``name==version``.  Blank lines and
    ``#`` comments are ignored (comments may appear after the spec).
    """
    path = Path(file_path)
    if not path.is_file():
        print(f"Error: file not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    packages = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                # Strip trailing comments, then whitespace.
                line = raw_line.split("#", 1)[0].strip()
                if not line:
                    continue
                # Accept optional spaces around ``==`` so ``pkg == 1.2``
                # also works.  Allow the usual version characters.
                m = re.match(
                    r"^([A-Za-z0-9_.\-]+(?:\s*==\s*[A-Za-z0-9_.\-+!]+)?)",
                    line,
                )
                if m:
                    # Normalise ``pkg == 1.2`` → ``pkg==1.2``.
                    packages.append(re.sub(r"\s+", "", m.group(1)))
    except OSError as e:
        print(f"Error reading file {file_path}: {e}", file=sys.stderr)
        sys.exit(1)

    return packages


# ---------------------------------------------------------------------------
# Async driver
# ---------------------------------------------------------------------------


async def run(args) -> int:
    """Top-level async runner.  Returns the process exit code."""
    global DOWNLOAD_DIR, MAX_FILE_SIZE

    # ---- resolve mirror --------------------------------------------------
    # Order of precedence: explicit -p / -c / -m, otherwise DEFAULT_MIRROR
    # (which is now "pypi").  -p / -c / -m are mutually exclusive.
    if args.pypi:
        mirror_key = "pypi"
    elif args.china:
        mirror_key = "tsinghua"
    elif args.mirror:
        mirror_key = args.mirror
    else:
        mirror_key = DEFAULT_MIRROR

    mirror_base = MIRRORS[mirror_key]
    # Only PyPI-style mirrors expose the ``/simple/<pkg>/`` layout;
    # the runflare mirror uses a slightly different path.
    is_simple_index = mirror_key in ("pypi", "tsinghua")

    # ---- resolve download directory --------------------------------------
    if args.directory:
        DOWNLOAD_DIR = Path(args.directory).expanduser().resolve()
        if not DOWNLOAD_DIR.is_dir():
            print(
                f"Error: download directory does not exist: {DOWNLOAD_DIR}",
                file=sys.stderr,
            )
            return 1

    # ---- apply optional size-cap override -------------------------------
    if args.max_size is not None:
        MAX_FILE_SIZE = int(args.max_size * 1024 * 1024)

    # ---- collect packages ------------------------------------------------
    packages = list(args.packages)
    if args.file:
        file_pkgs = load_packages_from_file(args.file)
        print(f"Loaded {len(file_pkgs)} package(s) from {args.file}")
        packages.extend(file_pkgs)

    if not packages:
        return 2

    # Deduplicate case-insensitively while preserving order.  Note that
    # ``name`` and ``name==1.2`` are distinct keys, so both would survive.
    seen, unique = set(), []
    for p in packages:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    packages = unique

    concurrency = max(1, args.jobs)
    print(f"Mirror:        {mirror_key} ({mirror_base})")
    print(f"Download dir:  {DOWNLOAD_DIR}")
    print(f"Concurrency:   {concurrency}")
    print(f"Size limit:    {MAX_FILE_SIZE / (1024 * 1024):.2f} MiB")
    print(f"Integrity:     enabled (tar + zip/wheel)")
    print(f"Processing {len(packages)} package(s)...\n")

    start_time = time.time()

    timeout = httpx.Timeout(
        connect=PAGE_TIMEOUT,
        read=DOWNLOAD_TIMEOUT,
        write=DOWNLOAD_TIMEOUT,
        pool=PAGE_TIMEOUT,
    )
    limits = httpx.Limits(
        max_connections=concurrency + 2,
        max_keepalive_connections=concurrency,
    )
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        },
        limits=limits,
    ) as client:
        tasks = [
            process_package(client, pkg, mirror_base, is_simple_index, semaphore)
            for pkg in packages
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)

    elapsed = time.time() - start_time

    # ---- summarise -------------------------------------------------------
    buckets = {"ok": [], "exists": [], "skipped": [], "too_large": [], "failed": []}
    for pkg, status in results:
        buckets.setdefault(status, []).append(pkg)

    if buckets["ok"]:
        print("\nSuccessfully downloaded:")
        for pkg in buckets["ok"]:
            print(f"  ✓ {pkg}")
    if buckets["exists"]:
        print("\nAlready present:")
        for pkg in buckets["exists"]:
            print(f"  • {pkg}")
    if buckets["skipped"]:
        print("\nSkipped (arch-specific, no pure source/wheel available):")
        for pkg in buckets["skipped"]:
            print(f"  ⚠ {pkg}")
    if buckets["too_large"]:
        print(f"\nSkipped (over {MAX_FILE_SIZE / (1024 * 1024):.2f} MiB):")
        for pkg in buckets["too_large"]:
            print(f"  ⚠ {pkg}")
    if buckets["failed"]:
        print("\nFailed to download:")
        for pkg in buckets["failed"]:
            print(f"  ✗ {pkg}")

    print(
        f"\nDone in {elapsed:.1f}s — "
        f"{len(buckets['ok'])} downloaded, "
        f"{len(buckets['exists'])} already present, "
        f"{len(buckets['skipped'])} skipped (arch), "
        f"{len(buckets['too_large'])} skipped (size), "
        f"{len(buckets['failed'])} failed"
    )

    return 1 if buckets["failed"] else 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        prog="pipget.py",
        description=(
            "Download packages from a PyPI mirror.  Source distributions "
            "and pure-Python wheels are preferred; arch-specific wheels "
            "and files larger than the size cap are skipped.  Archives "
            "are validated (tar / zip / wheel) after download."
        ),
        epilog=(
            "Package specs: 'name' or 'name==version' "
            "(e.g. 'aiohttp==3.5.16').  "
            "Mirror selection: default is official PyPI. Use -c for "
            "Tsinghua (China), -m for another mirror by name. "
            "-p / -c / -m are mutually exclusive."
        ),
    )
    parser.add_argument("packages", nargs="*", help="Package name(s) to download.")
    parser.add_argument(
        "-f",
        "--file",
        dest="file",
        metavar="FILE",
        help=(
            "Read package specs from FILE (one per line; blank lines and "
            "'#' comments are ignored).  Each line may be 'name' or "
            "'name==version'."
        ),
    )
    parser.add_argument(
        "-d",
        "--dir",
        dest="directory",
        metavar="DIR",
        help="Download directory (default: current directory).",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        dest="jobs",
        type=int,
        default=DEFAULT_CONCURRENCY,
        metavar="N",
        help=f"Concurrent downloads (default: {DEFAULT_CONCURRENCY}).",
    )
    parser.add_argument(
        "--max-size",
        dest="max_size",
        type=float,
        default=None,
        metavar="MiB",
        help=(
            f"Skip files larger than this (in MiB). "
            f"Default: {MAX_FILE_SIZE // (1024 * 1024)}."
        ),
    )

    mirror_group = parser.add_mutually_exclusive_group()
    mirror_group.add_argument(
        "-p",
        "--pypi",
        action="store_true",
        help="Download from official PyPI (this is the default).",
    )
    mirror_group.add_argument(
        "-c",
        "--china",
        action="store_true",
        help="Download from Tsinghua PyPI mirror.",
    )
    mirror_group.add_argument(
        "-m",
        "--mirror",
        choices=list(MIRRORS.keys()),
        help="Explicitly choose a mirror by name.",
    )

    args = parser.parse_args()

    if not args.packages and not args.file:
        parser.print_help()
        sys.exit(1)

    try:
        exit_code = asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(130)

    if exit_code == 2:
        parser.print_help()
        sys.exit(1)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
