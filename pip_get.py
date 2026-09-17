#!/data/data/com.termux/files/home/.local/bin/python
import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

console = Console()

# PyPI Mirror List for failover
MIRRORS = [
    "https://pypi.org/pypi",
    "https://pypi.tuna.tsinghua.edu.cn/pypi",
    "https://mirror-pypi.runflare.com/pypi",
]

RETRY_COUNT = 3
TIMEOUT = 30
CHUNK_THRESHOLD = 5 * 1024 * 1024  # 5 MB


def fetch_pypi_metadata(pkg_name: str) -> dict:
    """Fetch package metadata with failover across mirrors."""
    clean_name = pkg_name.split("==")[0].split(">=")[0].split("<=")[0].strip()

    for mirror in MIRRORS:
        url = f"{mirror}/{clean_name}/json"
        for _ in range(RETRY_COUNT):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "PyPIDownloader/1.0"}
                )
                with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                    if response.status == 200:
                        return json.loads(response.read().decode("utf-8"))
            except Exception:
                continue

    raise RuntimeError(f"Failed to fetch metadata for '{pkg_name}' from all mirrors.")


def select_best_release_file(metadata: dict, target_version: str | None = None) -> dict:
    """Select the preferred release file based on filtering rules."""
    releases = metadata.get("releases", {})
    version = target_version or metadata.get("info", {}).get("version")

    if not version or version not in releases:
        raise ValueError(f"Version '{version}' not found in package metadata.")

    files = releases[version]
    valid_files = []

    for file_info in files:
        filename = file_info["filename"].lower()

        # Rule 1: Exclude Darwin and Windows platform tags
        if any(tag in filename for tag in ["darwin", "win32", "win_amd64", "win_"]):
            continue

        # Rule 2: Exclude specific Python version wheels (keep generic/neutral ones)
        if filename.endswith(".whl") and "none-any" not in filename:
            continue

        valid_files.append(file_info)

    if not valid_files:
        raise RuntimeError(
            f"No suitable source or neutral wheel release files found for version {version}."
        )

    # Rule 3: Prefer .tar.gz over .whl
    sdist = [f for f in valid_files if f["filename"].endswith(".tar.gz")]
    if sdist:
        return sdist[0]

    whl = [f for f in valid_files if f["filename"].endswith(".whl")]
    if whl:
        return whl[0]

    return valid_files[0]


def verify_file_hash(dest_path: Path, expected_digests: dict) -> bool:
    """Verify downloaded file against expected hashes (sha256/md5)."""
    if "sha256" in expected_digests:
        algo, expected_hash = "sha256", expected_digests["sha256"]
    elif "md5" in expected_digests:
        algo, expected_hash = "md5", expected_digests["md5"]
    else:
        console.print(
            "[yellow]No known hash provided in metadata. Skipping hash verification.[/yellow]"
        )
        return True

    hasher = hashlib.new(algo)
    with open(dest_path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            hasher.update(chunk)

    calculated_hash = hasher.hexdigest().lower()
    if calculated_hash == expected_hash.lower():
        console.print(
            f"[bold green]✓ Integrity check passed ({algo.upper()})[/bold green]"
        )
        return True
    else:
        console.print(
            f"[bold red]✗ Hash verification failed! Expected: {expected_hash}, Got: {calculated_hash}[/bold red]"
        )
        return False


def build_progress_bar() -> Progress:
    """Build a rich progress bar display."""
    return Progress(
        TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
        BarColumn(bar_width=None),
        "[progress.percentage]{task.percentage:>3.1f}%",
        "•",
        DownloadColumn(),
        "•",
        TransferSpeedColumn(),
        "•",
        TextColumn("[cyan]Elapsed:[/cyan]"),
        TimeElapsedColumn(),
        "•",
        TextColumn("[cyan]ETA:[/cyan]"),
        TimeRemainingColumn(),
        console=console,
    )


def download_with_pycurl(url: str, dest_path: Path, file_size: int):
    """Download with PyCurl, supporting resume (RANGE header) and Rich progress bar."""
    import pycurl

    resume_byte = dest_path.stat().st_size if dest_path.exists() else 0
    mode = "ab" if resume_byte > 0 else "wb"

    with build_progress_bar() as progress:
        task_id = progress.add_task(
            "download",
            filename=dest_path.name,
            total=file_size,
            completed=resume_byte,
        )

        def write_callback(data):
            size = len(data)
            progress.update(task_id, advance=size)
            return file_file.write(data)

        for attempt in range(1, RETRY_COUNT + 1):
            try:
                with open(dest_path, mode) as file_file:
                    c = pycurl.Curl()
                    c.setopt(c.URL, url)
                    c.setopt(c.WRITEFUNCTION, write_callback)
                    c.setopt(c.TIMEOUT, TIMEOUT)
                    c.setopt(c.CONNECTTIMEOUT, TIMEOUT)
                    c.setopt(c.FOLLOWLOCATION, True)

                    if resume_byte > 0:
                        c.setopt(c.RESUME_FROM, resume_byte)

                    c.perform()
                    c.close()
                return
            except pycurl.Error as e:
                resume_byte = dest_path.stat().st_size if dest_path.exists() else 0
                mode = "ab"
                if attempt == RETRY_COUNT:
                    raise


def download_with_requests(url: str, dest_path: Path, file_size: int, use_chunks: bool):
    """Download with Requests, supporting resume (Range header) and Rich progress bar."""
    import requests

    resume_byte = dest_path.stat().st_size if dest_path.exists() else 0
    mode = "ab" if resume_byte > 0 else "wb"
    headers = {}

    if resume_byte > 0:
        headers["Range"] = f"bytes={resume_byte}-"

    with build_progress_bar() as progress:
        task_id = progress.add_task(
            "download",
            filename=dest_path.name,
            total=file_size,
            completed=resume_byte,
        )

        for attempt in range(1, RETRY_COUNT + 1):
            try:
                response = requests.get(
                    url, headers=headers, stream=True, timeout=TIMEOUT
                )

                # If range header isn't supported by mirror, fallback to overwrite
                if response.status_code == 200 and resume_byte > 0:
                    mode = "wb"
                    resume_byte = 0
                    progress.update(task_id, completed=0)

                response.raise_for_status()

                chunk_size = 1024 * 1024 if use_chunks else 1024 * 64
                with open(dest_path, mode) as f:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            progress.update(task_id, advance=len(chunk))
                return
            except requests.RequestException as e:
                resume_byte = dest_path.stat().st_size if dest_path.exists() else 0
                mode = "ab"
                if resume_byte > 0:
                    headers["Range"] = f"bytes={resume_byte}-"
                if attempt == RETRY_COUNT:
                    raise


def download_with_aria2c(url: str, dest_path: Path):
    """Download using aria2c via subprocess (native support for resume & progress bar)."""
    cmd = [
        "aria2c",
        "--continue=true",  # Enable resumed downloads
        f"--max-tries={RETRY_COUNT}",
        f"--timeout={TIMEOUT}",
        f"--dir={dest_path.parent.resolve()}",
        f"--out={dest_path.name}",
        url,
    ]
    subprocess.run(cmd, check=True)


def download_file(url: str, dest_path: Path, file_size: int, backend: str):
    """Route download requests to the designated backend tool."""
    is_chunked = file_size > CHUNK_THRESHOLD
    size_mb = file_size / (1024 * 1024)

    console.print(
        f"File size: [cyan]{size_mb:.2f} MB[/cyan] | Chunked mode: [cyan]{is_chunked}[/cyan]"
    )

    # Check if download is already complete
    if dest_path.exists() and dest_path.stat().st_size == file_size:
        console.print(
            "[yellow]Local file matches full size. Skipping download...[/yellow]"
        )
        return

    if backend == "pycurl":
        download_with_pycurl(url, dest_path, file_size)
    elif backend == "requests":
        download_with_requests(url, dest_path, file_size, is_chunked)
    elif backend == "aria2c":
        download_with_aria2c(url, dest_path)
    else:
        raise ValueError(f"Unsupported backend engine: {backend}")


def read_packages_from_file(file_path: Path) -> list:
    """Read package specifiers from a file (one per line).

    Lines starting with '#' and blank lines are ignored.
    Inline comments after '#' are also stripped.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Package list file not found: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"Path is not a regular file: {file_path}")

    packages = []
    with file_path.open("r", encoding="utf-8") as f:
        for lineno, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip inline comments
            if "#" in line:
                line = line.split("#", 1)[0].strip()
            if not line:
                continue
            # Very light sanity check for whitespace inside spec
            for token in line.split():
                packages.append(token)
    return packages


def print_usage():
    console.print(
        "[red]Usage:[/red]\n"
        "  python script.py <pkg1> [pkg2==1.0.0 ...] [options]\n"
        "  python script.py -f packages.txt [options]\n"
        "\n"
        "[bold]Options:[/bold]\n"
        "  -f, --file <path>      Read package specifiers from a file (one per line).\n"
        "                         Blank lines and lines starting with '#' are ignored.\n"
        "                         Can be combined with positional package args.\n"
        "  --backend=<engine>     Download backend: pycurl | requests | aria2c\n"
        "                         (default: pycurl)\n"
        "  -h, --help             Show this help message and exit.\n"
    )


def main():
    args = sys.argv[1:]
    backend = "pycurl"
    packages = []
    file_paths = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            print_usage()
            sys.exit(0)
        elif arg in ("-f", "--file"):
            if i + 1 >= len(args):
                console.print("[red]Error: -f/--file requires a path argument.[/red]")
                sys.exit(1)
            file_paths.append(Path(args[i + 1]))
            i += 2
            continue
        elif arg.startswith("--file="):
            file_paths.append(Path(arg.split("=", 1)[1].strip()))
        elif arg.startswith("--backend="):
            backend = arg.split("=", 1)[1].strip()
        elif arg.startswith("-"):
            console.print(f"[red]Error: Unknown option '{arg}'.[/red]")
            print_usage()
            sys.exit(1)
        else:
            packages.append(arg)
        i += 1

    # Load packages from files (in order, preserving duplicates for retry attempts)
    for fp in file_paths:
        try:
            loaded = read_packages_from_file(fp)
            console.print(f"[cyan]Loaded {len(loaded)} package(s) from {fp}[/cyan]")
            packages.extend(loaded)
        except Exception as e:
            console.print(f"[bold red]Failed to read '{fp}': {e}[/bold red]")
            sys.exit(1)

    if not packages:
        console.print("[red]Error: No package name specified.[/red]")
        print_usage()
        sys.exit(1)

    if backend not in ("pycurl", "requests", "aria2c"):
        console.print(
            f"[red]Error: Unknown backend '{backend}'. "
            "Choose from: pycurl, requests, aria2c.[/red]"
        )
        sys.exit(1)

    output_dir = Path.cwd()

    for pkg_spec in packages:
        console.print(
            f"\n[bold underline]Processing Package Specifier: {pkg_spec}[/bold underline]"
        )

        if "==" in pkg_spec:
            pkg_name, target_ver = pkg_spec.split("==", 1)
        else:
            pkg_name, target_ver = pkg_spec, None

        try:
            metadata = fetch_pypi_metadata(pkg_name)
            file_meta = select_best_release_file(metadata, target_ver)

            download_url = file_meta["url"]
            filename = file_meta["filename"]
            file_size = file_meta.get("size", 0)
            digests = file_meta.get("digests", {})
            target_path = output_dir / filename

            console.print(f"Selected file : [green]{filename}[/green]")
            console.print(f"Target URL    : {download_url}")

            download_file(download_url, target_path, file_size, backend)

            if not verify_file_hash(target_path, digests):
                console.print(
                    "[bold red]Deleting corrupted/incomplete file...[/bold red]"
                )
                target_path.unlink(missing_ok=True)

        except Exception as err:
            console.print(f"[bold red]Failed to process '{pkg_spec}': {err}[/bold red]")


if __name__ == "__main__":
    main()
