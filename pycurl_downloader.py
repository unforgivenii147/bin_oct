#!/data/data/com.termux/files/home/.local/bin/python
"""
Download URLs from a file (one per line) using pycurl
with a multiprocessing pool of fixed 8 workers.

On success, the URL is removed from the input file.
On failure, the URL stays in the input file.
Per-URL timeout: 50 seconds.

Usage:
    python download.py urls.txt
"""

import multiprocessing as mp
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import pycurl

WORKERS = 8
OUTPUT_DIR = Path("downloads")
TIMEOUT = 30  # seconds — download timeout AND pool wait timeout
CONNECT_TIMEOUT = 5
USER_AGENT = "Mozilla/5.0 (compatible; PyCurlDownloader/1.0)"


def filename_from_url(url: str) -> str:
    """Derive a safe local filename from a URL."""
    parsed = urlparse(url)
    path = unquote(parsed.path)
    name = Path(path).name or "index"

    if parsed.query:
        safe_query = "".join(
            c if c.isalnum() or c in "-_." else "_" for c in parsed.query
        )
        name = f"{name}_{safe_query}"

    name = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    return name or "index"


def unique_path(directory: Path, name: str) -> Path:
    """Return a non-colliding path inside `directory`."""
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    i = 1
    while True:
        candidate = directory / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def download_one(url: str) -> tuple[str, bool, str]:
    """Download a single URL with pycurl. Returns (url, success, message)."""
    url = url.strip()
    if not url:
        return (url, False, "empty url")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    name = filename_from_url(url)
    out_path = unique_path(OUTPUT_DIR, name)
    tmp_path = out_path.with_suffix(out_path.suffix + ".part")

    try:
        with tmp_path.open("wb") as fp:
            c = pycurl.Curl()
            c.setopt(pycurl.URL, url)
            c.setopt(pycurl.WRITEDATA, fp)
            c.setopt(pycurl.FOLLOWLOCATION, True)
            c.setopt(pycurl.MAXREDIRS, 10)
            c.setopt(pycurl.TIMEOUT, TIMEOUT)
            c.setopt(pycurl.CONNECTTIMEOUT, CONNECT_TIMEOUT)
            c.setopt(pycurl.USERAGENT, USER_AGENT)
            c.setopt(pycurl.NOSIGNAL, 1)
            c.setopt(pycurl.FAILONERROR, False)
            c.setopt(pycurl.SSL_VERIFYPEER, False)
            c.setopt(pycurl.SSL_VERIFYHOST, False)

            try:
                c.perform()
                status = c.getinfo(pycurl.RESPONSE_CODE)
                c.close()
            except pycurl.error as e:
                c.close()
                tmp_path.unlink(missing_ok=True)
                return (url, False, f"curl error: {e}")

        if status >= 400:
            tmp_path.unlink(missing_ok=True)
            return (url, False, f"HTTP {status}")

        tmp_path.replace(out_path)
        size = out_path.stat().st_size
        return (url, True, f"{out_path.name} ({size} bytes)")

    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        return (url, False, f"exception: {e}")


def worker_init():
    """Ignore SIGINT in workers so Ctrl+C is handled by the main process."""
    import signal

    signal.signal(signal.SIGINT, signal.SIG_IGN)


def load_urls(path: Path) -> list[str]:
    """Read URLs from file, skipping blanks and comments."""
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def save_failed(path: Path, failed_urls: list[str]) -> None:
    """Rewrite the input file so it contains only the URLs that failed."""
    if failed_urls:
        path.write_text("\n".join(failed_urls) + "\n", encoding="utf-8")
    else:
        # All succeeded — truncate the file
        path.write_text("", encoding="utf-8")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <urls_file>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        sys.exit(1)

    urls = load_urls(input_path)
    if not urls:
        print("No URLs found in input file.")
        sys.exit(0)

    print(
        f"Downloading {len(urls)} URLs with {WORKERS} workers "
        f"(timeout {TIMEOUT}s each)..."
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Preserve original ordering info: {url -> first-seen index}
    original_order = {}
    for i, u in enumerate(urls):
        original_order.setdefault(u, i)

    failed_urls: set[str] = set()
    # URLs we never got a definitive result for are kept as failed
    processed_ok: set[str] = set()

    try:
        with mp.Pool(processes=WORKERS, initializer=worker_init) as pool:
            async_results = [
                (url, pool.apply_async(download_one, (url,))) for url in urls
            ]

            total = len(async_results)
            done = 0
            for url, ar in async_results:
                try:
                    result = ar.get(timeout=TIMEOUT + 5)
                except mp.TimeoutError:
                    result = (url, False, "timeout waiting for worker")
                except Exception as e:
                    result = (url, False, f"pool error: {e}")

                done += 1
                u, ok, msg = result
                if ok:
                    processed_ok.add(u)
                else:
                    failed_urls.add(u)

                status = "OK " if ok else "ERR"
                print(f"[{done}/{total}] {status} {u} -> {msg}")

    except KeyboardInterrupt:
        print("\nInterrupted by user. Any unprocessed URLs remain in the file.")
        # Any URL that wasn't confirmed OK is treated as failed (kept in file)
        for u in urls:
            if u not in processed_ok:
                failed_urls.add(u)

    # Write back only the failed URLs, preserving original file order
    kept_in_order = sorted(failed_urls, key=lambda u: original_order.get(u, 1 << 30))
    save_failed(input_path, kept_in_order)

    ok_count = len(processed_ok)
    fail_count = len(kept_in_order)
    print(f"\nDone. Success: {ok_count}, Failed: {fail_count}")
    print(f"Remaining URLs saved back to: {input_path}")
    print(f"Files saved in: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
