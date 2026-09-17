#!/data/data/com.termux/files/home/.local/bin/python
"""Extract various archive formats in the current directory using external tools.

This script scans the current working directory for supported archive files
(.7z, .zip, .rar, .tar, .tar.gz, .tar.bz2, .tar.xz, .tgz, .tbz2,
.txz, .gz, .bz2, .xz, .lz4, .lzma, .zst, .cab, .arj, .ace),
extracts each one into either the current directory (for multi-file archives) or
a subdirectory named after the archive (for single-file archives), and optionally
deletes the original archive file upon successful extraction.

Extraction is performed in parallel using a fixed pool of 8 worker processes
via multiprocessing.Pool.apply_async. Results are logged with loguru, including
per-archive status, extraction time, file counts, and a final summary.

The script requires external extraction tools (e.g., 7z, unzip, unrar, tar,
gunzip, bunzip2, unxz, lz4, unlzma, unzstd, cabextract, arj, unace)
to be installed and available on the system PATH. Unsupported formats are skipped;
missing tools cause failures with descriptive error messages.
Type annotations are provided throughout for strict type checking (mypy/pyright),
and all filesystem operations use pathlib.Path.
"""

import shutil
import subprocess
import time
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class ExtractionStats:
    """Statistics for a single archive extraction operation."""

    archive_path: Path
    status: str
    extraction_time: float
    output_dir: Path | None = None
    extracted_files: int = 0
    error_message: str | None = None
    original_size: int = 0

    def __str__(self) -> str:
        """Return a human-readable string representation of the stats."""
        size_mb: float = self.original_size / (1024 * 1024)
        status_icon: str = (
            "✓" if self.status == "success" else "✗" if self.status == "failed" else "○"
        )
        result: str = (
            f"{status_icon} {self.archive_path.name} [{size_mb:.1f}MB] - {self.status}"
        )
        if self.status == "success":
            result += f" ({self.extracted_files} files, {self.extraction_time:.1f}s)"
            if self.output_dir:
                result += f" → {self.output_dir.name}"
        elif self.status == "failed":
            result += f" - {self.error_message}"
        return result


class ArchiveExtractor:
    """Extract various archive formats using external tools."""

    EXTRACTION_COMMANDS: dict[str, list[str]] = {
        ".7z": ["7z", "x", "-y", "-o"],
        ".zip": ["unzip", "-o"],
        ".rar": ["unrar", "x", "-y"],
        ".tar": ["tar", "-xf"],
        ".tar.gz": ["tar", "-xzf"],
        ".tgz": ["tar", "-xzf"],
        ".tar.bz2": ["tar", "-xjf"],
        ".tbz2": ["tar", "-xjf"],
        ".tar.xz": ["tar", "-xJf"],
        ".txz": ["tar", "-xJf"],
        ".gz": ["gunzip", "-f"],
        ".bz2": ["bunzip2", "-f"],
        ".xz": ["unxz", "-f"],
        ".lz4": ["lz4", "-d", "-f"],
        ".lzma": ["unlzma", "-f"],
        ".zst": ["unzstd", "-f"],
        ".cab": ["cabextract"],
        ".arj": ["arj", "x", "-y"],
        ".ace": ["unace", "x"],
    }

    SINGLE_FILE_EXTENSIONS: set[str] = {".gz", ".bz2", ".xz", ".lz4", ".lzma", ".zst"}

    def __init__(self, current_dir: Path) -> None:
        """Initialize the extractor with the working directory."""
        self.current_dir: Path = current_dir
        self._check_available_tools()

    def _check_available_tools(self) -> dict[str, bool]:
        """Check which extraction tools are available on the system."""
        available: dict[str, bool] = {}
        for ext, cmd in self.EXTRACTION_COMMANDS.items():
            tool: str = cmd[0]
            if shutil.which(tool):
                available[ext] = True
            else:
                available[ext] = False
        return available

    def _check_if_single_file_archive(self, archive_path: Path) -> bool:
        """Determine if the archive contains a single file at its root."""
        if archive_path.suffix.lower() in self.SINGLE_FILE_EXTENSIONS:
            return True

        try:
            suffix: str = archive_path.suffix.lower()
            if suffix == ".zip":
                result: subprocess.CompletedProcess[str] = subprocess.run(
                    ["unzip", "-l", str(archive_path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    lines: list[str] = result.stdout.strip().split("\n")
                    entries: list[str] = []
                    for line in lines[3:-2]:
                        parts: list[str] = line.strip().split()
                        if len(parts) >= 4:
                            entries.append(" ".join(parts[3:]))
                    if entries:
                        first_parts: set[str] = set()
                        for entry in entries:
                            parts: tuple[str, ...] = Path(entry).parts
                            if parts:
                                first_parts.add(parts[0])
                        return len(first_parts) == 1 and not all(
                            "/" not in e for e in entries
                        )
            elif suffix in [
                ".tar",
                ".tar.gz",
                ".tar.bz2",
                ".tar.xz",
                ".tgz",
                ".tbz2",
                ".txz",
            ]:
                result: subprocess.CompletedProcess[str] = subprocess.run(
                    ["tar", "-tf", str(archive_path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    entries: list[str] = [
                        line.strip()
                        for line in result.stdout.split("\n")
                        if line.strip()
                    ]
                    if entries:
                        first_parts: set[str] = set()
                        for entry in entries:
                            parts: tuple[str, ...] = Path(entry).parts
                            if parts:
                                first_parts.add(parts[0])
                        return len(first_parts) == 1 and not all(
                            "/" not in e for e in entries
                        )
        except (subprocess.TimeoutExpired, Exception):
            pass
        return False

    def _get_output_directory(self, archive_path: Path) -> Path:
        """Generate the output directory name for an archive."""
        stem: str = archive_path.name
        for ext in [".tar.gz", ".tar.bz2", ".tar.xz", ".tar.lz4"]:
            if stem.endswith(ext):
                stem = stem[: -len(ext)]
                break
        else:
            stem = archive_path.stem
        return self.current_dir / stem

    def _count_files(self, directory: Path) -> int:
        """Count the number of files in a directory recursively."""
        try:
            return sum(1 for _ in directory.rglob("*") if _.is_file())
        except Exception:
            return 0

    def extract_archive(self, archive_path: Path) -> ExtractionStats:
        """Extract a single archive file and return statistics."""
        start_time: float = time.time()
        original_size: int = archive_path.stat().st_size if archive_path.exists() else 0
        stats: ExtractionStats = ExtractionStats(
            archive_path=archive_path,
            status="failed",
            extraction_time=0,
            original_size=original_size,
        )
        archive_name: str = archive_path.name.lower()
        ext: str | None = None
        for possible_ext in sorted(
            self.EXTRACTION_COMMANDS.keys(), key=len, reverse=True
        ):
            if archive_name.endswith(possible_ext):
                ext = possible_ext
                break
        if not ext:
            stats.status = "skipped"
            stats.error_message = f"Unsupported format: {archive_path.suffix}"
            stats.extraction_time = time.time() - start_time
            return stats

        tool: str = self.EXTRACTION_COMMANDS[ext][0]
        if not shutil.which(tool):
            stats.status = "failed"
            stats.error_message = f"Tool '{tool}' not found"
            stats.extraction_time = time.time() - start_time
            return stats

        try:
            needs_subdir: bool = self._check_if_single_file_archive(archive_path)
            output_dir: Path = (
                self._get_output_directory(archive_path)
                if needs_subdir
                else self.current_dir
            )
            if needs_subdir:
                output_dir.mkdir(exist_ok=True)

            cmd: list[str] = list(self.EXTRACTION_COMMANDS[ext])
            if ext == ".7z":
                cmd.append(str(archive_path))
                cmd[-2] = f"-o{output_dir}"
            elif ext == ".zip":
                cmd.extend([str(archive_path), "-d", str(output_dir)])
            elif ext in [
                ".tar",
                ".tar.gz",
                ".tar.bz2",
                ".tar.xz",
                ".tgz",
                ".tbz2",
                ".txz",
            ]:
                cmd.extend(["-C", str(output_dir), str(archive_path)])
            elif ext == ".rar":
                cmd.extend([str(archive_path), str(output_dir)])
            elif ext == ".lz4":
                output_file: Path = output_dir / archive_path.stem
                cmd.extend([str(archive_path), str(output_file)])
            elif ext in [".gz", ".bz2", ".xz", ".lzma", ".zst"]:
                temp_archive: Path = output_dir / archive_path.name
                shutil.copy2(archive_path, temp_archive)

                cmd.append(str(temp_archive))
                cwd: Path = output_dir
                result: subprocess.CompletedProcess[str] = subprocess.run(
                    cmd, cwd=cwd, capture_output=True, text=True, timeout=300
                )
                if result.returncode == 0:
                    temp_archive.unlink(missing_ok=True)
                    stats.status = "success"
                    stats.output_dir = output_dir
                    stats.extracted_files = self._count_files(output_dir)
                    stats.extraction_time = time.time() - start_time
                    archive_path.unlink()
                    return stats
                else:
                    raise subprocess.CalledProcessError(
                        result.returncode,
                        cmd,
                        output=result.stdout,
                        stderr=result.stderr,
                    )
            else:
                cmd.append(str(archive_path))
                if output_dir != self.current_dir:
                    cmd.append(str(output_dir))

            if ext not in [".gz", ".bz2", ".xz", ".lzma", ".zst"]:
                result: subprocess.CompletedProcess[str] = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    cwd=self.current_dir,
                )
                if result.returncode != 0:
                    raise subprocess.CalledProcessError(
                        result.returncode,
                        cmd,
                        output=result.stdout,
                        stderr=result.stderr,
                    )

            if needs_subdir:
                extracted_count: int = self._count_files(output_dir)
            else:
                extracted_count: int = self._count_files(self.current_dir)
            stats.status = "success"
            stats.output_dir = output_dir if needs_subdir else None
            stats.extracted_files = extracted_count
            stats.extraction_time = time.time() - start_time
            try:
                archive_path.unlink()
            except Exception as e:
                stats.error_message = f"Extracted but couldn't remove original: {e}"
        except subprocess.CalledProcessError as e:
            stats.error_message = e.stderr.strip() if e.stderr else str(e)
            stats.extraction_time = time.time() - start_time
        except subprocess.TimeoutExpired:
            stats.error_message = "Extraction timed out (300s)"
            stats.extraction_time = time.time() - start_time
        except Exception as e:
            stats.error_message = str(e)
            stats.extraction_time = time.time() - start_time
        return stats


def find_archives(directory: Path) -> list[Path]:
    """Find all supported archive files in the given directory."""
    archive_extensions: set[str] = {
        ".7z",
        ".zip",
        ".rar",
        ".tar",
        ".tar.gz",
        ".tar.bz2",
        ".tar.xz",
        ".tgz",
        ".tbz2",
        ".txz",
        ".gz",
        ".bz2",
        ".xz",
        ".lz4",
        ".lzma",
        ".zst",
        ".cab",
        ".arj",
        ".ace",
    }

    archives: list[Path] = []
    for item in directory.iterdir():
        if item.is_file():
            name_lower: str = item.name.lower()
            for ext in archive_extensions:
                if name_lower.endswith(ext):
                    archives.append(item)
                    break
    return archives


def main() -> int:
    """Main entry point for the script."""
    current_dir: Path = Path.cwd()
    print(f"Scanning for archivesin: {current_dir}")
    archives: list[Path] = find_archives(current_dir)
    if not archives:
        print("No archive files found.")
        return 0

    print(f"Found {len(archives)} archive(s):")
    for archive in archives:
        size_mb: float = archive.stat().st_size / (1024 * 1024)
        print(f"  • {archive.name} ({size_mb:.1f} MB)")

    max_workers: int = 8  # Fixed pool size as requested
    print(f"Processing with {max_workers} parallel worker(s)...")

    extractor: ArchiveExtractor = ArchiveExtractor(current_dir)
    results: list[ExtractionStats] = []
    start_time: float = time.time()

    with Pool(processes=max_workers) as pool:
        async_results: list[tuple[Any, Path]] = []
        for archive in archives:
            async_result: Any = pool.apply_async(extractor.extract_archive, (archive,))
            async_results.append((async_result, archive))

        for async_result, archive in async_results:
            try:
                result: ExtractionStats = async_result.get()
                results.append(result)
                print(str(result))
            except Exception as e:
                logger.error(f"✗ {archive.name} - Worker error: {e}")

    total_time: float = time.time() - start_time
    successful: int = sum(1 for r in results if r.status == "success")
    failed: int = sum(1 for r in results if r.status == "failed")
    skipped: int = sum(1 for r in results if r.status == "skipped")

    print(f"\n{'=' * 40}")
    print("SUMMARY")
    print(f"{'=' * 40}")
    print(f"Total archives: {len(archives)}")
    print(f"✓ Successfully extracted: {successful}")
    print(f"✗ Failed: {failed}")
    print(f"○ Skipped: {skipped}")
    print(f"Total time: {total_time:.1f}s")

    if results:
        print("\nDetailed results:")
        for result in results:
            print(f"  {result}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
