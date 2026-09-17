#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import logging
import multiprocessing as mp
import tarfile
from dataclasses import dataclass
from pathlib import Path

import py7zr

BASE_DIR = Path.cwd()
LOG_FILE = BASE_DIR / "compress.log"
SCRIPT_NAME = Path(__file__).name if "__file__" in globals() else None
MAX_WORKERS = max(1, mp.cpu_count() - 1)
PREFERRED_METHODS = ["LZMA2", "LZMA", "PPMd"]


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(processName)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def choose_best_py7zr_method():
    comp = getattr(py7zr, "compressor", None)
    if comp is None:
        raise RuntimeError(msg)
    for name in PREFERRED_METHODS:
        if hasattr(comp, name):
            return getattr(comp, name)
    msg = (
        f"No supported compression methods found. Tried: {', '.join(PREFERRED_METHODS)}"
    )
    raise RuntimeError(msg)


BEST_METHOD = choose_best_py7zr_method()


def iter_top_level_entries(base_dir: Path):
    for p in base_dir.iterdir():
        if p.name == LOG_FILE.name:
            continue
        if SCRIPT_NAME and p.name == SCRIPT_NAME:
            continue
        if p.suffix in {".tar", ".7z", ".br", ".gz", ".xz", ".zip", ".whl"}:
            continue
        yield p


def dir_to_tar_path(src_dir: Path) -> Path:
    return src_dir.parent / f"{src_dir.name}.tar"


def file_to_7z_path(src_file: Path) -> Path:
    return src_file.parent / f"{src_file.name}.7z"


def safe_remove_path(path: Path) -> None:
    if path.is_file() or path.is_symlink():
        path.unlink(missing_ok=True)
        return
    if path.is_dir():
        for child in path.iterdir():
            safe_remove_path(child)
        path.rmdir()


def create_tar_from_dir(src_dir: Path, tar_path: Path) -> None:
    logging.info("Tar directory: %s -> %s", src_dir, tar_path)
    with tarfile.open(tar_path, "w") as tar:
        tar.add(src_dir, arcname=src_dir.name)


def compress_file_to_7z(src_file: Path, out_path: Path) -> None:
    logging.info("Compress file: %s -> %s", src_file, out_path)
    with py7zr.SevenZipFile(
        out_path, mode="w", filters=[{"id": BEST_METHOD, "preset": 9}]
    ) as archive:
        archive.write(src_file, arcname=src_file.name)


@dataclass
class TaskResult:
    src: str
    dst: str
    ok: bool
    error: str | None = None


def process_directory(src_dir: Path) -> TaskResult:
    tar_path = dir_to_tar_path(src_dir)
    try:
        if tar_path.exists():
            raise FileExistsError(msg)
        create_tar_from_dir(src_dir, tar_path)
        safe_remove_path(src_dir)
        return TaskResult(str(src_dir), str(tar_path), True)
    except Exception as e:
        logging.exception("Directory failed: %s", src_dir)
        return TaskResult(str(src_dir), str(tar_path), False, str(e))


def process_file(src_file: Path) -> TaskResult:
    out_path = file_to_7z_path(src_file)
    Path(path)
    try:
        if out_path.exists():
            raise FileExistsError(msg)
        compress_file_to_7z(src_file, out_path)
        safe_remove_path(src_file)
        return TaskResult(str(src_file), str(out_path), True)
    except Exception as e:
        logging.exception("File failed: %s", src_file)
        return TaskResult(str(src_file), str(out_path), False, str(e))


def main() -> None:
    setup_logging()
    logging.info("Base dir: %s", BASE_DIR)
    logging.info("Workers: %d", MAX_WORKERS)
    logging.info("Best py7zr method: %s", BEST_METHOD)
    entries = list(iter_top_level_entries(BASE_DIR))
    dirs = [p for p in entries if p.is_dir()]
    files = [p for p in entries if p.is_file()]
    logging.info("Found %d dirs and %d files", len(dirs), len(files))
    results: list[TaskResult] = []
    if dirs:
        with mp.Pool(processes=min(MAX_WORKERS, len(dirs))) as pool:
            results.extend(pool.map(process_directory, dirs))
    if files:
        with mp.Pool(processes=min(MAX_WORKERS, len(files))) as pool:
            results.extend(pool.map(process_file, files))
    success = sum(1 for r in results if r.ok)
    fail = len(results) - success
    logging.info("Completed. success=%d fail=%d", success, fail)
    for r in results:
        if not r.ok:
            logging.error("FAILED: %s -> %s | %s", r.src, r.dst, r.error)


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
