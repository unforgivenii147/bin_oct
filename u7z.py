#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import logging
import multiprocessing as mp
import tarfile
from pathlib import Path

import py7zr

BASE_DIR = Path.cwd()
LOG_FILE = BASE_DIR / "decompress.log"
MAX_WORKERS = max(1, mp.cpu_count() - 1)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(processName)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def iter_archives(base_dir: Path):
    for p in base_dir.iterdir():
        if p.is_file() and p.suffix in {".tar", ".7z"}:
            yield p


def tar_extract_dir_for(archive_path: Path) -> Path:
    return archive_path.parent / archive_path.stem


def seven_zip_extract_dir_for(archive_path: Path) -> Path:
    return archive_path.parent / archive_path.stem


def safe_extract_tar(archive_path: Path, target_dir: Path) -> None:
    logging.info("Extracting TAR: %s -> %s", archive_path, target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r") as tar:
        tar.extractall(path=target_dir)


def safe_extract_7z(archive_path: Path, target_dir: Path) -> None:
    logging.info("Extracting 7Z: %s -> %s", archive_path, target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    with py7zr.SevenZipFile(archive_path, mode="r") as archive:
        archive.extractall(path=target_dir)


def remove_path(path: Path) -> None:
    if path.is_file() or path.is_symlink():
        path.unlink(missing_ok=True)
        return
    if path.is_dir():
        for child in path.iterdir():
            remove_path(child)
        path.rmdir()


class TaskResult:
    def __init__(self, src: str, dst: str, ok: bool, error: str | None = None) -> None:
        self.src = src
        self.dst = dst
        self.ok = ok
        self.error = error


def process_archive(archive_path: Path) -> TaskResult:
    try:
        if archive_path.suffix == ".tar":
            target_dir = tar_extract_dir_for(archive_path)
            if target_dir.exists():
                msg = "error: target dir exists"
                raise FileExistsError(msg)
            safe_extract_tar(archive_path, target_dir)
        elif archive_path.suffix == ".7z":
            target_dir = seven_zip_extract_dir_for(archive_path)
            if target_dir.exists():
                msg = "error: target exists"
                raise FileExistsError(msg)
            safe_extract_7z(archive_path, target_dir)
        else:
            msg = "error ."
            raise ValueError(msg)
        remove_path(archive_path)
        return TaskResult(str(archive_path), str(target_dir), True)
    except Exception as e:
        logging.exception("Failed to decompress %s", archive_path)
        return TaskResult(str(archive_path), "", False, str(e))


def main() -> None:
    setup_logging()
    logging.info("Starting decompression in %s", BASE_DIR)
    logging.info("Workers: %d", MAX_WORKERS)
    archives = list(iter_archives(BASE_DIR))
    logging.info("Found %d archives", len(archives))
    results: list[TaskResult] = []
    if archives:
        with mp.Pool(processes=min(MAX_WORKERS, len(archives))) as pool:
            results.extend(pool.map(process_archive, archives))
    success = sum(1 for r in results if r.ok)
    fail = len(results) - success
    logging.info("Completed. success=%d fail=%d", success, fail)
    for r in results:
        if not r.ok:
            logging.error("FAILED: %s | %s", r.src, r.error)


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
