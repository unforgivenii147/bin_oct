#!/data/data/com.termux/files/home/.local/bin/python
"""Compress each non-hidden subdirectory as `<name>.tar.br` and each regular file as `<name>.br` in the current directory: build tar archives in memory, Brotli-compress with quality 11 in chunks of 64 KiB, run both job types through `multiprocessing.pool.starmap` on a fixed pool of 8 workers, and log with loguru."""

import io
import sys
import tarfile
from multiprocessing.pool import Pool
from pathlib import Path
from typing import BinaryIO, Final

import brotli  # type: ignore[import-untyped]
from loguru import logger

MAX_WORKERS: Final[int] = 8
BROTLI_QUALITY: Final[int] = 11
CHUNK_SIZE: Final[int] = 1024 * 64


def compress_stream(input_stream: BinaryIO, output_file_path: Path) -> None:
    """Brotli-compress ``input_stream`` into ``output_file_path`` in ``CHUNK_SIZE`` chunks."""
    compressor: brotli.Compressor = brotli.Compressor(quality=BROTLI_QUALITY)
    with output_file_path.open("wb") as f_out:
        while True:
            chunk: bytes = input_stream.read(CHUNK_SIZE)
            if not chunk:
                break
            f_out.write(compressor.process(chunk))
        f_out.write(compressor.finish())


def process_directory(dir_path: Path) -> tuple[Path, bool, str | None]:
    """Tar ``dir_path`` in memory and Brotli-compress it to `<dir>.tar.br`.

    Returns ``(path, success, error_message_or_None)``.
    """
    output_br: Path = dir_path.with_name(f"{dir_path.name}.tar.br")
    tar_buffer: io.BytesIO = io.BytesIO()
    try:
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            tar.add(dir_path, arcname=dir_path.name)
        tar_buffer.seek(0)
        compress_stream(tar_buffer, output_br)
        return dir_path, True, None
    except Exception as e:
        return dir_path, False, f"Failed to archive directory {dir_path.name}: {e}"


def process_file(file_path: Path) -> tuple[Path, bool, str | None]:
    """Brotli-compress ``file_path`` to `<file>.br`.

    Returns ``(path, success, error_message_or_None)``.
    """
    output_br: Path = file_path.with_name(f"{file_path.name}.br")
    try:
        with file_path.open("rb") as f_in:
            compress_stream(f_in, output_br)
        return file_path, True, None
    except Exception as e:
        return file_path, False, f"Failed to compress file {file_path.name}: {e}"


def _dispatch(job: tuple[Path, bool]) -> tuple[Path, bool, str | None]:
    """Route a single starmap job to :func:`process_directory` or :func:`process_file`."""
    path, is_dir = job
    return process_directory(path) if is_dir else process_file(path)


def main() -> None:
    """CLI entry point: discover targets in the cwd and compress them in parallel."""
    current_dir: Path = Path(".")
    script_name: str = Path(__file__).name

    subdirs: list[Path] = [
        d for d in current_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
    ]
    files: list[Path] = [
        f
        for f in current_dir.iterdir()
        if f.is_file() and f.suffix != ".br" and f.name != script_name
    ]

    if not subdirs and not files:
        logger.info("No files or subdirectories found to compress.")
        return

    logger.info(
        "🚀 Found {} subdirs to TAR+BR, and {} files to BR.",
        len(subdirs),
        len(files),
    )
    logger.info(
        "⚡ Starting parallel processing pool (Quality Level: {})...",
        BROTLI_QUALITY,
    )

    jobs: list[tuple[Path, bool]] = [
        *((d, True) for d in subdirs),
        *((f, False) for f in files),
    ]

    success_count: int = 0
    error_count: int = 0

    with Pool(processes=MAX_WORKERS) as pool:
        for path, success, error in pool.imap_unordered(_dispatch, jobs):
            if success:
                logger.info("✅ Compressed: {}", path.name)
                success_count += 1
            else:
                logger.error("❌ {}", error)
                error_count += 1

    logger.info(
        "🎉 Done. {} succeeded, {} failed.",
        success_count,
        error_count,
    )


if __name__ == "__main__":
    raise SystemExit(main())
