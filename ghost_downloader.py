#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a multi-threaded concurrent download manager CLI tool named Ghost-CLI.

The script must:
- Use argparse to accept a required `url` positional argument, optional `-o/--output`,
  optional `-c/--chunks` (default 8) for the number of chunks, and optional `-ua/--user-agent`
  (default a modern Chrome UA string).
- Use the `requests` library to issue a HEAD request, read `Content-Length` and `Accept-Ranges`,
  and fall back to single-stream download if the size is unknown or ranges are unsupported.
- Use `multiprocessing.Pool.apply_async` with a fixed pool of 8 workers to download byte-range
  chunks concurrently, writing each chunk to a `<filename>.part<N>` file.
- Use `tqdm` to display a single progress bar over the total file size, updated as chunks complete.
- Reassemble the part files into the final output and remove the parts afterward.
- Use `loguru` for all logging output.
- Use `pathlib.Path` for all filesystem operations.
- Include full type annotations and concise docstrings on every function.
"""

from __future__ import annotations

import argparse
from multiprocessing.pool import ApplyResult, Pool
from pathlib import Path

import requests
from loguru import logger
from tqdm import tqdm

DEFAULT_CHUNKS: int = 8
POOL_WORKERS: int = 8
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
CHUNK_STREAM_SIZE: int = 1024 * 64
HEAD_TIMEOUT: int = 15
GET_TIMEOUT: int = 30


def parse_args() -> argparse.Namespace:
    """Parse and return command-line arguments for Ghost-CLI."""
    parser = argparse.ArgumentParser(
        description="Ghost-CLI: A lightweight multi-threaded concurrent download manager."
    )
    parser.add_argument("url", help="The direct file HTTP/HTTPS URL to download")
    parser.add_argument("-o", "--output", help="Output file path or filename")
    parser.add_argument(
        "-c",
        "--chunks",
        type=int,
        default=DEFAULT_CHUNKS,
        help=f"Number of parallel chunk threads (default: {DEFAULT_CHUNKS})",
    )
    parser.add_argument(
        "-ua",
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="Custom User-Agent to emulate browser fingerprints and bypass restrictions",
    )
    return parser.parse_args()


def download_chunk(
    url: str,
    start_byte: int,
    end_byte: int,
    chunk_id: int,
    headers: dict[str, str],
    filename: str,
) -> tuple[str, int]:
    """
    Download a single byte-range chunk of a file.

    Args:
        url: The source URL.
        start_byte: Inclusive start byte of the range.
        end_byte: Inclusive end byte of the range.
        chunk_id: Index of this chunk, used for the part filename.
        headers: HTTP headers to send with the request.
        filename: Base output filename used for the part file.

    Returns:
        A tuple of (part_filename, start_byte).
    """
    chunk_headers: dict[str, str] = headers.copy()
    chunk_headers["Range"] = f"bytes={start_byte}-{end_byte}"
    part_filename: str = f"{filename}.part{chunk_id}"
    part_path: Path = Path(part_filename)

    with requests.get(
        url, headers=chunk_headers, stream=True, timeout=GET_TIMEOUT
    ) as r:
        r.raise_for_status()
        with part_path.open("wb") as f:
            for data in r.iter_content(chunk_size=CHUNK_STREAM_SIZE):
                if data:
                    f.write(data)

    return part_filename, start_byte


def _resolve_filename(url: str, output: str | None) -> str:
    """Derive the output filename from the CLI or the URL."""
    if output:
        return output
    candidate: str = url.split("/")[-1].split("?")[0]
    return candidate or "downloaded_file"


def _single_stream_download(
    url: str,
    headers: dict[str, str],
    filename: str,
    total_size: int,
) -> None:
    """Perform a simple single-stream download with a progress bar."""
    with (
        requests.get(url, headers=headers, stream=True, timeout=GET_TIMEOUT) as r,
        Path(filename).open("wb") as f,
        tqdm(
            total=total_size,
            unit="B",
            unit_scale=True,
            desc=filename,
        ) as pbar,
    ):
        r.raise_for_status()
        for data in r.iter_content(chunk_size=CHUNK_STREAM_SIZE):
            if data:
                f.write(data)
                pbar.update(len(data))
    logger.success(f"Download complete: {filename}")


def main() -> int:
    """Entry point for the Ghost-CLI download manager."""
    args: argparse.Namespace = parse_args()
    url: str = args.url
    num_chunks: int = args.chunks

    headers: dict[str, str] = {
        "User-Agent": args.user_agent,
        "Accept": "*/*",
        "Connection": "keep-alive",
    }

    try:
        head_response = requests.head(
            url, headers=headers, allow_redirects=True, timeout=HEAD_TIMEOUT
        )
        head_response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Error reaching target URL: {e}")
        return 1

    total_size: int = int(head_response.headers.get("content-length", 0))
    accept_ranges: str = head_response.headers.get("accept-ranges", "bytes")

    filename: str = _resolve_filename(url, args.output)

    if total_size == 0:
        logger.warning(
            "Web Server did not return a content length. "
            "Falling back to single-stream download."
        )
        num_chunks = 1

    if accept_ranges != "bytes" and num_chunks > 1:
        logger.warning(
            "Target server does not support byte-range slicing. "
            "Falling back to single-stream download."
        )
        num_chunks = 1

    print(f"Target File: {filename}")
    if total_size:
        print(f"File Size: {total_size / (1024 * 1024):.2f} MB")
    else:
        print("File Size: Unknown")
    print(f"Thread Slices: {num_chunks}")

    if num_chunks == 1:
        _single_stream_download(url, headers, filename, total_size)
        return 0

    chunk_size: int = total_size // num_chunks
    part_files: list[str | None] = [None] * num_chunks

    print("Slicing chunks and initializing network connections...")

    pool: Pool = Pool(processes=POOL_WORKERS)
    try:
        with tqdm(
            total=total_size, unit="B", unit_scale=True, desc="Downloading"
        ) as pbar:
            async_results: list[ApplyResult[tuple[str, int]]] = []
            for i in range(num_chunks):
                start_byte: int = i * chunk_size
                end_byte: int = (
                    total_size - 1
                    if i == num_chunks - 1
                    else start_byte + chunk_size - 1
                )
                async_results.append(
                    pool.apply_async(
                        download_chunk,
                        args=(url, start_byte, end_byte, i, headers, filename),
                    )
                )

            for result in async_results:
                try:
                    part_file, _start_byte = result.get()
                    idx: int = int(part_file.split(".part")[-1])
                    part_files[idx] = part_file
                    actual_part_size: int = Path(part_file).stat().st_size
                    pbar.update(actual_part_size)
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Critical worker exception: {e}")
                    for pf in part_files:
                        if pf:
                            p = Path(pf)
                            if p.exists():
                                p.unlink()
                    return 1
    finally:
        pool.close()
        pool.join()

    print("Assembling downloaded slices into final file...")
    final_path: Path = Path(filename)
    with final_path.open("wb") as final_file:
        for part_file in part_files:
            if part_file is None:
                continue
            part_path: Path = Path(part_file)
            if part_path.exists():
                with part_path.open("rb") as pf:
                    final_file.write(pf.read())
                part_path.unlink()

    logger.success(f"Download complete and assembled successfully: {filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
