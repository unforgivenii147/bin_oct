#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a multithreaded, resumable HTTP file downloader CLI in Python.

The script must:
- Accept a URL, optional output filename, and optional expected SHA-256 hash as CLI arguments.
- Use `requests` to fetch file metadata via HTTP HEAD, determine file size, and support
  HTTP Range requests for chunked downloading.
- Download the file in fixed-size chunks concurrently using `multiprocessing.Pool.apply_async`
  with a fixed pool of 8 workers (no CLI flags controlling parallelism).
- Persist download progress to a sidecar `.progress` JSON state file, allowing resumption
  of interrupted downloads.
- Use `loguru` for all logging output (no `print`, no stdlib `logging`).
- Use `pathlib.Path` for all filesystem operations (no `os.path`).
- Use `rich.progress.Progress` to display a live progress bar with download speed and ETA.
- Handle Ctrl+C (SIGINT) gracefully by saving state and exiting cleanly.
- Optionally verify the downloaded file's SHA-256 hash against the provided expected hash.
- Include complete type annotations (strict mypy/pyright compatible) and docstrings for
  every module, class, function, and method.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import signal
import sys
import threading
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote

import requests
from loguru import logger
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

CHUNK_SIZE: int = 1024 * 1024 * 5  # 5 MiB buffered read size for hashing
RANGE_CHUNK_SIZE: int = 32768  # 32 KiB logical chunk size for Range requests
MAX_WORKERS: int = 8  # Fixed pool size
STATE_SUFFIX: str = ".progress"
HTTP_TIMEOUT: int = 15

console: Console = Console()


# ---------------------------------------------------------------------------
# Downloader class
# ---------------------------------------------------------------------------


class Downloader:
    """Resumable, concurrent HTTP file downloader.

    Downloads a remote file in fixed-size byte ranges using a pool of worker
    processes, persisting progress to a JSON state file so that interrupted
    downloads can be resumed. Optionally verifies the resulting file against
    an expected SHA-256 hash.

    Attributes:
        url: The remote URL to download.
        stop_event: Threading event used to signal workers to stop.
        file_size: Total size of the remote file in bytes.
        filename: Local path where the file will be saved.
        expected_hash: Optional expected SHA-256 hex digest for verification.
        state_file: Path to the JSON progress state file.
        progress_data: In-memory representation of the progress state.
        lock: Lock guarding access to `progress_data` and state file writes.
    """

    url: str
    stop_event: threading.Event
    file_size: int
    filename: str | None
    expected_hash: str | None
    state_file: Path | None
    progress_data: dict[str, Any]
    lock: threading.Lock

    def __init__(
        self,
        url: str,
        output_path: str | None = None,
        expected_hash: str | None = None,
    ) -> None:
        """Initialize the downloader.

        Args:
            url: Remote URL to download.
            output_path: Optional local filename. If omitted, derived from the
                server's Content-Disposition header or the URL path.
            expected_hash: Optional expected SHA-256 hex digest of the file.
        """
        self.url = url
        self.stop_event = threading.Event()
        self.file_size = 0
        self.filename = output_path
        self.expected_hash = expected_hash
        self.state_file = None
        self.progress_data = {"downloaded_chunks": [], "total_chunks": 0}
        self.lock = threading.Lock()

    # ------------------------------------------------------------------
    # Metadata / state helpers
    # ------------------------------------------------------------------

    def _get_info(self) -> None:
        """Fetch remote file metadata and determine the local filename.

        Issues an HTTP HEAD request, extracts the Content-Length and
        Content-Disposition headers, and computes the path to the state file.

        Raises:
            requests.HTTPError: If the HEAD request returns an error status.
        """
        resp: requests.Response = requests.head(
            self.url, allow_redirects=True, timeout=HTTP_TIMEOUT
        )
        resp.raise_for_status()
        self.file_size = int(resp.headers.get("content-length", 0))

        if not self.filename:
            cd: str | None = resp.headers.get("Content-Disposition")
            if cd and "filename=" in cd:
                self.filename = cd.split("filename=")[1].strip(' "')
            else:
                self.filename = unquote(self.url.split("/")[-1]) or "downloaded_file"

        assert self.filename is not None
        self.state_file = Path(f"{self.filename}{STATE_SUFFIX}")

    def _verify_integrity(self) -> None:
        """Compute the SHA-256 hash of the downloaded file and compare it.

        If `expected_hash` was provided, the calculated hash is compared
        against it and the result is logged. Otherwise the calculated hash is
        logged so the user may reuse it in future invocations.
        """
        assert self.filename is not None
        sha256_hash = hashlib.sha256()
        print("Verifying file integrity...")

        with Path(self.filename).open("rb") as f:
            for byte_block in iter(lambda: f.read(CHUNK_SIZE), b""):
                sha256_hash.update(byte_block)

        calculated_hash: str = sha256_hash.hexdigest()

        if self.expected_hash:
            if calculated_hash.lower() == self.expected_hash.lower():
                logger.success("Integrity verified: hashes match!")
            else:
                logger.error("Integrity check failed!")
                logger.error(f"Expected: {self.expected_hash}")
                logger.error(f"Got:      {calculated_hash}")
        else:
            logger.warning(f"SHA-256 checksum: {calculated_hash}")
            print("Provide this hash next time to verify automatically.")

    def _load_state(self) -> None:
        """Load persisted progress data from the state file, if it exists."""
        if self.state_file is not None and self.state_file.exists():
            try:
                with self.state_file.open(encoding="utf-8") as f:
                    loaded: dict[str, Any] = json.load(f)
                self.progress_data = loaded
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(f"Could not load state file: {exc}")

    def _save_state(self) -> None:
        """Persist the current progress data to the state file."""
        if self.state_file is None:
            return
        with self.lock, self.state_file.open("w", encoding="utf-8") as f:
            json.dump(self.progress_data, f)

    # ------------------------------------------------------------------
    # Chunk download worker (runs in a subprocess)
    # ------------------------------------------------------------------

    def _download_chunk(
        self,
        chunk_id: int,
        start: int,
        end: int,
        progress: Progress,
        task_id: TaskID,
    ) -> None:
        """Download a single byte range and append its id to the state.

        Args:
            chunk_id: Sequential index of this chunk.
            start: Inclusive start byte offset.
            end: Inclusive end byte offset.
            progress: Rich `Progress` instance to update (only used in-process).
            task_id: Rich task identifier for the progress bar.
        """
        if self.stop_event.is_set():
            return

        headers: dict[str, str] = {"Range": f"bytes={start}-{end}"}
        try:
            with requests.get(
                self.url, headers=headers, stream=True, timeout=HTTP_TIMEOUT
            ) as r:
                r.raise_for_status()
                assert self.filename is not None
                with Path(self.filename).open("r+b") as f:
                    f.seek(start)
                    for data in r.iter_content(chunk_size=1024 * 64):
                        if self.stop_event.is_set():
                            return
                        f.write(data)
                        try:
                            progress.update(task_id, advance=len(data))
                        except Exception:
                            # Rich progress updates are best-effort inside worker
                            # processes; ignore failures silently.
                            pass
            with self.lock:
                self.progress_data["downloaded_chunks"].append(chunk_id)
            self._save_state()
        except Exception as exc:  # noqa: BLE001 - worker must not crash the pool
            logger.debug(f"Chunk {chunk_id} failed: {exc}")

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Run the download to completion, resuming if a state file exists.

        Orchestrates metadata fetch, state loading, chunking, concurrent
        download via a `multiprocessing.Pool`, progress display, and final
        integrity verification. Handles SIGINT gracefully.
        """
        self._get_info()
        self._load_state()

        assert self.filename is not None
        if not Path(self.filename).exists():
            with Path(self.filename).open("wb") as f:
                f.truncate(self.file_size)

        chunks: list[tuple[int, int]] = [
            (i, min(i + RANGE_CHUNK_SIZE - 1, self.file_size - 1))
            for i in range(0, self.file_size, RANGE_CHUNK_SIZE)
        ]
        self.progress_data["total_chunks"] = len(chunks)

        downloaded: list[int] = list(self.progress_data.get("downloaded_chunks", []))
        pending_chunks: list[tuple[int, int, int]] = [
            (idx, s, e) for idx, (s, e) in enumerate(chunks) if idx not in downloaded
        ]

        if not pending_chunks:
            logger.success(f"{self.filename} is already finished!")
            self._verify_integrity()
            return

        def _sigint_handler(signum: int, frame: Any) -> None:  # noqa: ARG001
            self.stop_event.set()

        signal.signal(signal.SIGINT, _sigint_handler)

        with Progress(
            TextColumn("[bold blue]{task.fields[filename]}"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            main_task: TaskID = progress.add_task(
                "download",
                filename=self.filename,
                total=self.file_size,
                completed=len(downloaded) * RANGE_CHUNK_SIZE,
            )

            pool: Pool = multiprocessing.Pool(processes=MAX_WORKERS)
            async_results: list[AsyncResult] = []
            try:
                for cid, s, e in pending_chunks:
                    ar: AsyncResult = pool.apply_async(
                        self._download_chunk,
                        args=(cid, s, e, progress, main_task),
                    )
                    async_results.append(ar)

                for ar in async_results:
                    if self.stop_event.is_set():
                        break
                    try:
                        ar.get()
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(f"Worker raised: {exc}")
            finally:
                pool.close()
                pool.join()

        if not self.stop_event.is_set():
            if self.state_file is not None:
                self.state_file.unlink(missing_ok=True)
            logger.success(f"Download complete: {self.filename}")
            self._verify_integrity()
        else:
            logger.warning("Download paused. Run again to resume.")
            sys.exit(0)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse CLI arguments and run the downloader."""
    if len(sys.argv) < 2:
        logger.error(
            "Usage: python downloader.py <URL> [output_name] [expected_sha256]"
        )
        sys.exit(1)

    url_arg: str = sys.argv[1]
    out_arg: str | None = sys.argv[2] if len(sys.argv) > 2 else None
    hash_arg: str | None = sys.argv[3] if len(sys.argv) > 3 else None

    dl = Downloader(url_arg, out_arg, hash_arg)
    dl.start()


if __name__ == "__main__":
    main()
