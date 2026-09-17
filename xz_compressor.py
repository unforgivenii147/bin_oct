#!/data/data/com.termux/files/home/.local/bin/python
"""
LZMA Compression Utility with Parallel Processing

This script recursively compresses or decompresses files using LZMA compression
with optional parallel processing, tar directory support, and file exclusion patterns.
It provides both rich and basic output formats with detailed statistics.
"""

import argparse
import lzma
import multiprocessing as mp
import shutil
import sys
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path

from dh import fsz
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

RICH_AVAILABLE = True
EXCLUDED_EXTENSIONS = {
    ".xz",
    ".lzma",
    ".7z",
    ".gz",
    ".bz2",
    ".zip",
    ".rar",
    ".tar",
    ".tgz",
    ".tbz2",
    ".txz",
    ".tlz",
    ".lz",
    ".lz4",
    ".lzo",
    ".sz",
    ".snappy",
    ".zlib",
    ".deflate",
    ".flac",
    ".mp3",
    ".aac",
    ".ogg",
    ".wma",
    ".opus",
    ".m4a",
    ".wavpack",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".avif",
    ".heic",
    ".heif",
    ".mp4",
    ".avi",
    ".mkv",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".wasm",
    ".whl",
    ".egg",
    ".deb",
    ".rpm",
    ".apk",
    ".ipa",
    ".pyc",
    ".pyo",
    ".class",
    ".o",
    ".obj",
    ".iso",
    ".img",
    ".dmg",
    ".vdi",
    ".vmdk",
    ".qcow2",
}


@dataclass
class CompressionResult:
    """
    Data class to store compression/decompression results.

    Attributes:
        path: Path to the processed file
        original_size: Size of the file before processing
        processed_size: Size of the file after processing
        success: Whether the operation succeeded
        error: Error message if operation failed
        duration: Time taken for the operation
        original_deleted: Whether the original file was deleted
        operation: Type of operation performed
        was_tarred: Whether the file was tarred before compression
    """

    path: Path
    original_size: int
    processed_size: int
    success: bool
    error: str | None = None
    duration: float = 0.0
    original_deleted: bool = False
    operation: str = "compress"
    was_tarred: bool = False


def tar_directory(
    directory: Path, output_path: Path, delete_original: bool = False
) -> tuple[int, bool]:
    """
    Create a tar archive of a directory.

    Args:
        directory: Directory to tar
        output_path: Path for the output tar file
        delete_original: Whether to delete the original directory after tarring

    Returns:
        Tuple of (tar_size, success_flag)
    """
    try:
        dir_size = sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())
        with tarfile.open(output_path, "w") as tar:
            tar.add(directory, arcname=directory.name)
        tar_size = output_path.stat().st_size
        if delete_original:
            shutil.rmtree(directory, ignore_errors=True)
        return tar_size, True
    except Exception as e:
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        print(f"❌ Error tarring {directory.name}: {e}")
        return 0, False


def untar_file(tar_path: Path, extract_dir: Path, delete_tar: bool = False) -> bool:
    """
    Extract a tar archive.

    Args:
        tar_path: Path to the tar file
        extract_dir: Directory to extract to
        delete_tar: Whether to delete the tar file after extraction

    Returns:
        True if successful, False otherwise
    """
    try:
        with tarfile.open(tar_path, "r") as tar:
            tar.extractall(extract_dir, filter="data")
        if delete_tar:
            tar_path.unlink(missing_ok=True)
        return True
    except Exception as e:
        print(f"❌ Error extracting {tar_path.name}: {e}")
        return False


def compress_file_streaming(
    input_path: Path,
    output_path: Path,
    preset: int = 7,
    threads: int = 4,
    chunk_size: int = 2 * 1024 * 1024,
    keep_original: bool = False,
    was_tarred: bool = False,
) -> CompressionResult:
    """
    Compress a file using LZMA streaming.

    Args:
        input_path: Path to input file
        output_path: Path for compressed output
        preset: LZMA compression preset (0-9)
        threads: Number of threads for compression
        chunk_size: Size of chunks to process
        keep_original: Whether to keep the original file
        was_tarred: Whether the input was a tar file

    Returns:
        CompressionResult object with compression details
    """
    start = time.time()
    try:
        original_size = input_path.stat().st_size
        if original_size == 0:
            return CompressionResult(
                input_path,
                0,
                0,
                False,
                "Empty file",
                time.time() - start,
                was_tarred=was_tarred,
            )
        compressed_size = 0
        with open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
            compressor = lzma.LZMACompressor(
                format=lzma.FORMAT_XZ,
                check=lzma.CHECK_CRC64,
                preset=preset,
                filters=[{"id": lzma.FILTER_LZMA2, "preset": preset}],
            )
            while True:
                chunk = f_in.read(chunk_size)
                if not chunk:
                    break
                compressed_chunk = compressor.compress(chunk)
                if compressed_chunk:
                    f_out.write(compressed_chunk)
                    compressed_size += len(compressed_chunk)
            remaining = compressor.flush()
            if remaining:
                f_out.write(remaining)
                compressed_size += len(remaining)
        if not keep_original and output_path.exists():
            input_path.unlink(missing_ok=True)
            original_deleted = True
        else:
            original_deleted = False
        return CompressionResult(
            path=input_path,
            original_size=original_size,
            processed_size=compressed_size,
            success=True,
            duration=time.time() - start,
            original_deleted=original_deleted,
            operation="compress",
            was_tarred=was_tarred,
        )
    except Exception as e:
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        return CompressionResult(
            input_path,
            original_size=input_path.stat().st_size if input_path.exists() else 0,
            processed_size=0,
            success=False,
            error=str(e),
            duration=time.time() - start,
            operation="compress",
            was_tarred=was_tarred,
        )


def decompress_file_streaming(
    input_path: Path,
    output_path: Path,
    chunk_size: int = 2 * 1024 * 1024,
    keep_original: bool = False,
) -> CompressionResult:
    """
    Decompress a file using LZMA streaming.

    Args:
        input_path: Path to compressed file
        output_path: Path for decompressed output
        chunk_size: Size of chunks to process
        keep_original: Whether to keep the compressed file

    Returns:
        CompressionResult object with decompression details
    """
    start = time.time()
    try:
        original_size = input_path.stat().st_size
        if original_size == 0:
            return CompressionResult(
                input_path,
                0,
                0,
                False,
                "Empty file",
                time.time() - start,
                operation="decompress",
            )
        decompressed_size = 0
        with lzma.open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
            while True:
                chunk = f_in.read(chunk_size)
                if not chunk:
                    break
                f_out.write(chunk)
                decompressed_size += len(chunk)
        if not keep_original:
            input_path.unlink(missing_ok=True)
            original_deleted = True
        else:
            original_deleted = False
        return CompressionResult(
            path=input_path,
            original_size=original_size,
            processed_size=decompressed_size,
            success=True,
            duration=time.time() - start,
            original_deleted=original_deleted,
            operation="decompress",
        )
    except Exception as e:
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        return CompressionResult(
            input_path,
            original_size=input_path.stat().st_size if input_path.exists() else 0,
            processed_size=0,
            success=False,
            error=str(e),
            duration=time.time() - start,
            operation="decompress",
        )


def process_subdirs_with_tar(
    directory: Path,
    preset: int = 7,
    threads: int = 4,
    workers: int = 4,
    keep_original: bool = False,
    exclude_patterns: list[str] | None = None,
) -> list[CompressionResult]:
    """
    Process subdirectories by tarring them first, then compressing.

    Args:
        directory: Root directory containing subdirectories
        preset: LZMA compression preset (0-9)
        threads: Number of threads for compression
        workers: Number of parallel workers
        keep_original: Whether to keep original files
        exclude_patterns: Patterns to exclude from processing

    Returns:
        List of CompressionResult objects
    """
    if exclude_patterns is None:
        exclude_patterns = []
    excluded_dirs = {
        ".git",
        ".svn",
        ".hg",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".env",
    }
    subdirs = [
        d
        for d in directory.iterdir()
        if d.is_dir()
        and not d.is_symlink()
        and d.name not in excluded_dirs
        and not any(pat in str(d) for pat in exclude_patterns)
    ]
    if not subdirs:
        print("📁 No subdirectories found to tar")
        return []
    print(f"📁 Found {len(subdirs)} subdirectories to tar...")
    results: list[CompressionResult] = []
    for i, subdir in enumerate(subdirs, 1):
        tar_path = subdir.parent / f"{subdir.name}.tar"
        print(f"  📦 [{i}/{len(subdirs)}] Tarring {subdir.name}...")
        dir_size = sum(f.stat().st_size for f in subdir.rglob("*") if f.is_file())
        _tar_size, success = tar_directory(
            subdir, tar_path, delete_original=not keep_original
        )
        if not success:
            continue
        xz_path = tar_path.with_suffix(".tar.xz")
        result = compress_file_streaming(
            tar_path,
            xz_path,
            preset,
            threads,
            keep_original=not keep_original,
            was_tarred=True,
        )
        results.append(result)
        if result.success:
            ratio = (
                (1 - result.processed_size / result.original_size) * 40
                if result.original_size
                else 0
            )
            print(
                f"    ✅ {fsz(dir_size)} → {fsz(result.processed_size)} ({ratio:.1f}%)"
            )
        else:
            print(f"    ❌ Failed compressing {tar_path.name}: {result.error}")
    return results


def should_compress_file(
    path: Path, exclude_extensions: set[str], exclude_patterns: list[str]
) -> bool:
    """
    Check if a file should be compressed.

    Args:
        path: Path to check
        exclude_extensions: Set of extensions to exclude
        exclude_patterns: List of patterns to exclude

    Returns:
        True if the file should be compressed, False otherwise
    """
    if path.is_symlink() or not path.is_file():
        return False
    if path.suffix.lower() in exclude_extensions:
        return False
    return not (exclude_patterns and any(pat in str(path) for pat in exclude_patterns))


def find_files_to_compress(
    directory: Path,
    exclude_extensions: set[str] | None = None,
    exclude_patterns: list[str] | None = None,
    extensions_filter: list[str] | None = None,
    skip_subdirs: bool = False,
) -> list[Path]:
    """
    Find files that should be compressed in a directory.

    Args:
        directory: Root directory to search
        exclude_extensions: Set of extensions to exclude
        exclude_patterns: List of patterns to exclude
        extensions_filter: List of extensions to include (None means all)
        skip_subdirs: Only search root directory if True

    Returns:
        Sorted list of file paths to compress
    """
    if exclude_extensions is None:
        exclude_extensions = EXCLUDED_EXTENSIONS
    if exclude_patterns is None:
        exclude_patterns = []
    files = []
    if extensions_filter:
        for ext in extensions_filter:
            ext = ext if ext.startswith(".") else f".{ext}"
            for p in directory.rglob(f"*{ext}"):
                if should_compress_file(p, exclude_extensions, exclude_patterns) and (
                    not skip_subdirs or p.parent == directory
                ):
                    files.append(p)
    else:
        for p in directory.rglob("*"):
            if should_compress_file(p, exclude_extensions, exclude_patterns) and (
                not skip_subdirs or p.parent == directory
            ):
                files.append(p)
    return sorted(set(files))


def find_files_to_decompress(
    directory: Path, exclude_patterns: list[str] | None = None
) -> list[Path]:
    """
    Find .xz files to decompress in a directory.

    Args:
        directory: Root directory to search
        exclude_patterns: List of patterns to exclude

    Returns:
        Sorted list of .xz file paths to decompress
    """
    if exclude_patterns is None:
        exclude_patterns = []
    files = [p for p in directory.rglob("*.xz") if p.is_file() and not p.is_symlink()]
    if exclude_patterns:
        files = [p for p in files if not any(pat in str(p) for pat in exclude_patterns)]
    return sorted(set(files))


def get_file_type_stats(files: list[Path]) -> dict:
    """
    Get statistics about file types in a list.

    Args:
        files: List of file paths

    Returns:
        Dictionary mapping file extensions to counts
    """
    type_stats = {}
    for path in files:
        ext = path.suffix.lower() or "[no extension]"
        type_stats[ext] = type_stats.get(ext, 0) + 1
    return dict(sorted(type_stats.items(), key=lambda x: x[1], reverse=True))


def print_results_rich(
    results: list[CompressionResult], directory: Path, operation: str
) -> None:
    """
    Print results using rich formatting.

    Args:
        results: List of CompressionResult objects
        directory: Root directory processed
        operation: Type of operation performed
    """
    console = Console()
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    total_original = sum(r.original_size for r in successful)
    total_processed = sum(r.processed_size for r in successful)
    total_duration = sum(r.duration for r in results)
    deleted_count = sum(1 for r in successful if r.original_deleted)
    tarred_count = sum(1 for r in successful if r.was_tarred)
    if operation == "compress":
        space_saved = total_original - total_processed
        avg_ratio = (
            sum((1 - r.processed_size / r.original_size) * 40 for r in successful)
            / len(successful)
            if successful
            else 0
        )
        operation_emoji = "🗜️"
        operation_name = "Compression"
        size_label = "Compressed"
    else:
        space_saved = total_processed - total_original
        avg_ratio = (
            sum((r.processed_size / r.original_size - 1) * 40 for r in successful)
            / len(successful)
            if successful
            else 0
        )
        operation_emoji = "📂"
        operation_name = "Decompression"
        size_label = "Decompressed"
    table = Table(
        title=f"{operation_emoji} LZMA {operation_name} Results",
        box=box.ROUNDED,
        title_style="bold cyan",
        header_style="bold white",
    )
    table.add_column("File", style="cyan", no_wrap=False)
    table.add_column("Original", justify="right", style="yellow")
    table.add_column(size_label, justify="right", style="green")
    table.add_column("Ratio", justify="right", style="magenta")
    table.add_column("Time", justify="right", style="dim")
    table.add_column("Type", justify="center")
    table.add_column("Status", justify="center")
    for result in sorted(successful, key=lambda x: x.original_size, reverse=True)[:20]:
        if operation == "compress":
            ratio = (
                (1 - result.processed_size / result.original_size) * 40
                if result.original_size > 0
                else 0
            )
        else:
            ratio = (
                (result.processed_size / result.original_size - 1) * 40
                if result.original_size > 0
                else 0
            )
        status = "🗑️ ✅" if result.original_deleted else "✅"
        file_type = "📦 tar" if result.was_tarred else "📄 file"
        try:
            file_display = str(result.path.relative_to(directory))
        except ValueError:
            file_display = str(result.path)
        table.add_row(
            file_display,
            fsz(result.original_size),
            fsz(result.processed_size),
            f"{ratio:.1f}%",
            f"{result.duration:.2f}s",
            file_type,
            status,
        )
    if len(successful) > 20:
        table.add_row(
            f"... and {len(successful) - 20} more files", "", "", "", "", "", ""
        )
    console.print(table)
    if failed:
        fail_table = Table(
            title="❌ Failed Files", box=box.ROUNDED, title_style="bold red"
        )
        fail_table.add_column("File", style="red")
        fail_table.add_column("Error", style="dim")
        for result in failed[:10]:
            try:
                file_display = str(result.path.relative_to(directory))
            except ValueError:
                file_display = str(result.path)
            fail_table.add_row(file_display, result.error or "Unknown error")
        if len(failed) > 10:
            fail_table.add_row(f"... and {len(failed) - 10} more failures", "")
        console.print(fail_table)
    summary_text = Text()
    summary_text.append(f"📊 {operation_name} Summary\n\n", style="bold cyan")
    summary_text.append("📁 Directory: ", style="dim")
    summary_text.append(f"{directory}\n", style="bold white")
    summary_text.append("Total files processed: ", style="dim")
    summary_text.append(f"{len(results)}\n", style="bold white")
    summary_text.append("✅ Successful: ", style="dim")
    summary_text.append(f"{len(successful)}\n", style="bold green")
    summary_text.append("❌ Failed: ", style="dim")
    summary_text.append(f"{len(failed)}\n", style="bold red")
    if tarred_count > 0:
        summary_text.append("📦 From tarred directories: ", style="dim")
        summary_text.append(f"{tarred_count}\n", style="bold yellow")
    summary_text.append("🗑️  Originals deleted: ", style="dim")
    summary_text.append(f"{deleted_count}\n", style="bold yellow")
    summary_text.append("\n💾 Total original size: ", style="dim")
    summary_text.append(f"{fsz(total_original)}\n", style="bold yellow")
    summary_text.append(
        f"{('🗜️' if operation == 'compress' else '📂')} Total {size_label.lower()} size: ",
        style="dim",
    )
    summary_text.append(f"{fsz(total_processed)}\n", style="bold green")
    if operation == "compress":
        summary_text.append("📈 Average compression: ", style="dim")
        summary_text.append(f"{avg_ratio:.1f}%\n", style="bold magenta")
        summary_text.append("🎉 Disk space freed: ", style="dim")
        summary_text.append(f"{fsz(space_saved)} ", style="bold cyan")
    else:
        summary_text.append("📈 Average expansion: ", style="dim")
        summary_text.append(f"{avg_ratio:.1f}%\n", style="bold magenta")
        summary_text.append("💾 Disk space used: ", style="dim")
        summary_text.append(f"{fsz(space_saved)} ", style="bold cyan")
    if total_original > 0 and operation == "compress":
        summary_text.append(
            f"({space_saved / total_original * 40:.1f}%)\n", style="bold cyan"
        )
    summary_text.append("⏱️  Total time: ", style="dim")
    summary_text.append(f"{total_duration:.2f}s ", style="bold white")
    if results:
        summary_text.append(
            f"(avg {total_duration / len(results):.2f}s per file)", style="dim"
        )
    console.print(Panel(summary_text, border_style="cyan"))


def print_results_basic(
    results: list[CompressionResult], directory: Path, operation: str
) -> None:
    """
    Print results using basic formatting.

    Args:
        results: List of CompressionResult objects
        directory: Root directory processed
        operation: Type of operation performed
    """
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    total_original = sum(r.original_size for r in successful)
    total_processed = sum(r.processed_size for r in successful)
    total_duration = sum(r.duration for r in results)
    deleted_count = sum(1 for r in successful if r.original_deleted)
    tarred_count = sum(1 for r in successful if r.was_tarred)
    if operation == "compress":
        space_saved = total_original - total_processed
        avg_ratio = (
            sum((1 - r.processed_size / r.original_size) * 40 for r in successful)
            / len(successful)
            if successful
            else 0
        )
        operation_name = "Compression"
        size_label = "Compressed"
    else:
        space_saved = total_processed - total_original
        avg_ratio = (
            sum((r.processed_size / r.original_size - 1) * 40 for r in successful)
            / len(successful)
            if successful
            else 0
        )
        operation_name = "Decompression"
        size_label = "Decompressed"
    print("\n" + "=" * 40)
    print(f"🗜️  LZMA {operation_name} Results")
    print(f"📁 Directory: {directory}")
    print("-" * 40)
    print(f"\n{'File':<40} {'Original':>12} {size_label:>12} {'Ratio':>8} {'Time':>8}")
    print("-" * 40)
    for result in sorted(successful, key=lambda x: x.original_size, reverse=True)[:20]:
        if operation == "compress":
            ratio = (
                (1 - result.processed_size / result.original_size) * 40
                if result.original_size > 0
                else 0
            )
        else:
            ratio = (
                (result.processed_size / result.original_size - 1) * 40
                if result.original_size > 0
                else 0
            )
        file_name = (
            result.path.name[:37] + "..."
            if len(result.path.name) > 40
            else result.path.name
        )
        type_indicator = "[tar]" if result.was_tarred else ""
        print(
            f"{file_name:<40} {fsz(result.original_size):>12} "
            f"{fsz(result.processed_size):>12} {ratio:>7.1f}% "
            f"{result.duration:>7.2f}s {type_indicator}"
        )
    if len(successful) > 20:
        print(f"... and {len(successful) - 20} more files")
    if failed:
        print(f"\n❌ Failed files ({len(failed)}):")
        for result in failed[:10]:
            print(f"  • {result.path.name}: {result.error}")
        if len(failed) > 10:
            print(f"  ... and {len(failed) - 10} more failures")
    print("\n" + "=" * 40)
    print(f"📊 {operation_name} Summary")
    print("-" * 40)
    print(f"Total files processed: {len(results)}")
    print(f"✅ Successful: {len(successful)}")
    print(f"❌ Failed: {len(failed)}")
    if tarred_count > 0:
        print(f"📦 From tarred directories: {tarred_count}")
    print(f"🗑️  Originals deleted: {deleted_count}")
    print(f"\n💾 Total original size: {fsz(total_original)}")
    print(
        f"{('🗜️' if operation == 'compress' else '📂')} Total {size_label.lower()} size: {fsz(total_processed)}"
    )
    if operation == "compress":
        print(f"📈 Average compression: {avg_ratio:.1f}%")
        print(
            f"🎉 Disk space freed: {fsz(space_saved)} "
            f"({(space_saved / total_original * 40 if total_original > 0 else 0):.1f}%)"
        )
    else:
        print(f"📈 Average expansion: {avg_ratio:.1f}%")
        print(f"💾 Disk space used: {fsz(space_saved)}")
    print(
        f"⏱️  Total time: {total_duration:.2f}s "
        f"(avg {total_duration / len(results):.2f}s per file)"
        if results
        else ""
    )
    print("-" * 40)


def process_file_worker(args: tuple) -> CompressionResult:
    """
    Worker function for parallel processing using mp.pool.apply_async.

    Args:
        args: Tuple containing (path, operation, preset, threads, keep_original)

    Returns:
        CompressionResult object
    """
    path, operation, preset, threads, keep_original = args
    try:
        if operation == "compress":
            output_path = path.with_suffix(path.suffix + ".xz")
            return compress_file_streaming(
                path,
                output_path,
                preset,
                threads,
                1024 * 1024,
                keep_original,
            )
        else:  # decompress
            output_path = path.with_suffix("")
            return decompress_file_streaming(
                path, output_path, 1024 * 1024, keep_original
            )
    except Exception as e:
        return CompressionResult(
            path=path,
            original_size=path.stat().st_size if path.exists() else 0,
            processed_size=0,
            success=False,
            error=str(e),
            operation=operation,
        )


def main() -> None:
    """Main entry point for the compression utility."""
    parser = argparse.ArgumentParser(
        description="🗜️  Recursively compress/decompress files using LZMA with parallel processing (deletes originals by default)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n  %(prog)s                          # Compress all files in current directory\n  %(prog)s -c                       # Compress all files (explicit)\n  %(prog)s -d                       # Decompress all .xz files\n  %(prog)s -c -t                    # Tar subdirectories first, then compress\n  %(prog)s -c -t /path/to/dir       # Tar subdirs in specific directory\n  %(prog)s -c -e txt log csv        # Compress only specific extensions\n  %(prog)s -c -p 7 --threads 4      # Custom preset and threads\n  %(prog)s -c -p 9 --threads 8      # Maximum compression with 8 threads\n  %(prog)s -c --keep-originals      # Keep original files when compressing\n  %(prog)s -d --keep-originals      # Keep compressed files when decompressing\n  %(prog)s -c --dry-run             # Preview compression without modifying\n  %(prog)s --exclude node_modules   # Exclude specific directories\n        ",
    )
    operation_group = parser.add_mutually_exclusive_group()
    operation_group.add_argument(
        "-c",
        "--compress",
        action="store_true",
        default=True,
        help="Compress files (default)",
    )
    operation_group.add_argument(
        "-d", "--decompress", action="store_true", help="Decompress .xz files"
    )
    parser.add_argument(
        "-t",
        "--tar-subdirs-first",
        action="store_true",
        help="Tar subdirectories first, then apply LZMA compression on the .tar files (only valid with -c/--compress)",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        type=str,
        help="Root directory to process files recursively (default: current directory)",
    )
    parser.add_argument(
        "-e",
        "--extensions",
        nargs="+",
        help="Compress only specific file extensions (e.g., txt log csv). Only valid with -c/--compress.",
    )
    parser.add_argument(
        "-p",
        "--preset",
        type=int,
        default=7,
        choices=range(10),
        help="LZMA compression preset (0-9, default: 7). Higher = better compression but slower.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=4,
        help="Number of threads for LZMA compression (default: 4)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=8,  # Changed to fixed 8 workers
        help="Number of parallel workers for processing multiple files (default: 8)",
    )
    parser.add_argument(
        "--keep-originals",
        action="store_true",
        help="Keep original files after processing (default: delete originals)",
    )
    parser.add_argument(
        "--exclude",
        nargs="+",
        default=[],
        help="Directory/file patterns to exclude from processing (e.g., node_modules .git)",
    )
    parser.add_argument(
        "--no-parallel", action="store_true", help="Disable parallel processing"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without actually modifying files",
    )
    parser.add_argument(
        "--no-skip-compressed",
        action="store_true",
        help="Do not skip already compressed files (dangerous, may double-compress). Only valid with -c/--compress.",
    )
    args = parser.parse_args()
    operation = "decompress" if args.decompress else "compress"
    if args.tar_subdirs_first and operation == "decompress":
        print("❌ Error: -t/--tar-subdirs-first is only valid with -c/--compress")
        sys.exit(1)
    if operation == "decompress" and (args.extensions or args.no_skip_compressed):
        print(
            "⚠️  Warning: -e/--extensions and --no-skip-compressed are ignored in decompression mode"
        )
    if operation == "decompress":
        print("ℹ️  Note: -p/--preset and --threads are ignored in decompression mode")
    if operation == "compress":
        if args.no_skip_compressed:
            exclude_extensions = {".xz"}
            print("⚠️  WARNING: Not skipping already compressed files!")
        else:
            exclude_extensions = EXCLUDED_EXTENSIONS
    else:
        exclude_extensions = set()
    directory = Path(args.directory).resolve()
    if not directory.exists():
        print(f"❌ Error: Directory '{directory}' does not exist")
        sys.exit(1)
    if not directory.is_dir():
        print(f"❌ Error: '{directory}' is not a directory")
        sys.exit(1)
    operation_name = "compression" if operation == "compress" else "decompression"
    print(f"🔍 Scanning directory for {operation_name}: {directory}")

    if operation == "compress":
        if args.tar_subdirs_first:
            print("📁 Mode: Tar subdirectories first, then LZMA compression")
            tar_results = process_subdirs_with_tar(
                directory,
                preset=args.preset,
                threads=args.threads,
                workers=1 if args.no_parallel else args.workers,
                keep_original=args.keep_originals,
                exclude_patterns=args.exclude,
            )
            print("\n📁 Processing individual files in root directory...")
            files = find_files_to_compress(
                directory,
                exclude_extensions=exclude_extensions,
                exclude_patterns=args.exclude,
                extensions_filter=args.extensions,
                skip_subdirs=True,
            )
            if files:
                print(f"📁 Found {len(files)} individual file(s) in root directory")
                for path in files:
                    print(f"  • {path.relative_to(directory)}")
            else:
                print("📁 No individual files in root directory")
            all_results = tar_results
        else:
            if args.extensions:
                print(
                    f"📁 Mode: Only specified extensions ({', '.join(args.extensions)})"
                )
            else:
                print(
                    "📁 Mode: ALL files (excluding already compressed formats and symlinks)"
                )
            if args.exclude:
                print(f"🚫 Excluding patterns: {', '.join(args.exclude)}")
            files = find_files_to_compress(
                directory,
                exclude_extensions=exclude_extensions,
                exclude_patterns=args.exclude,
                extensions_filter=args.extensions,
                skip_subdirs=False,
            )
            all_results = []
        if not args.tar_subdirs_first and (not files):
            print("❌ No files found to compress")
            sys.exit(0)
        if not args.tar_subdirs_first:
            print(f"📁 Found {len(files)} file(s) to compress")
            type_stats = get_file_type_stats(files)
            if type_stats:
                print("📊 File types found:")
                for ext, count in list(type_stats.items())[:10]:
                    print(f"  • {ext}: {count} file(s)")
                if len(type_stats) > 10:
                    print(f"  • ... and {len(type_stats) - 10} more types")
            total_size = sum(f.stat().st_size for f in files)
            print(f"💾 Total size: {fsz(total_size)}")
    else:
        print("📁 Mode: Decompressing .xz files")
        if args.exclude:
            print(f"🚫 Excluding patterns: {', '.join(args.exclude)}")
        files = find_files_to_decompress(directory, exclude_patterns=args.exclude)
        if not files:
            print("❌ No .xz files found to decompress")
            sys.exit(0)
        print(f"📁 Found {len(files)} .xz file(s) to decompress")
        total_size = sum(f.stat().st_size for f in files)
        print(f"💾 Total compressed size: {fsz(total_size)}")

    if args.dry_run:
        if args.tar_subdirs_first:
            print("\n🔍 DRY RUN - Would tar subdirectories and compress them with LZMA")
        else:
            print(
                f"\n🔍 DRY RUN - Would {operation} {len(files)} files ({fsz(total_size)})"
            )
        print("No files were modified.")
        return

    if not args.keep_originals:
        if operation == "compress":
            if args.tar_subdirs_first:
                print(
                    "⚠️  Subdirectories will be tarred and originals DELETED (use --keep-originals to preserve)"
                )
            else:
                print(
                    "⚠️  Originals will be DELETED after compression (use --keep-originals to preserve)"
                )
        else:
            print(
                "⚠️  Compressed .xz files will be DELETED after decompression (use --keep-originals to preserve)"
            )

    if operation == "compress":
        print(f"🎯 Compression preset: {args.preset}/9")
        print(f"🧵 LZMA threads: {args.threads}")

    workers = (
        1
        if args.no_parallel
        else min(
            args.workers, len(files) if not args.tar_subdirs_first else args.workers
        )
    )
    if not args.tar_subdirs_first:
        print(f"👷 Workers: {workers}")
    print()

    results = []

    # Use mp.pool.apply_async for parallel processing
    if args.tar_subdirs_first:
        results = all_results
        if files:
            print("🔄 Compressing individual files...")
            if workers > 1 and len(files) > 1:
                # Create arguments for worker function
                worker_args = [
                    (
                        path,
                        "compress",
                        args.preset,
                        args.threads,
                        args.keep_originals,
                    )
                    for path in files
                ]
                with mp.Pool(processes=workers) as pool:
                    async_results = [
                        pool.apply_async(process_file_worker, (arg,))
                        for arg in worker_args
                    ]
                    for async_result in async_results:
                        result = async_result.get()
                        results.append(result)
            else:
                for path in files:
                    result = process_file_worker(
                        (
                            path,
                            "compress",
                            args.preset,
                            args.threads,
                            args.keep_originals,
                        )
                    )
                    results.append(result)
    elif not args.tar_subdirs_first:
        print(f"🔄 {operation_name.capitalize()} files...")
        if workers > 1 and len(files) > 1:
            # Create arguments for worker function
            worker_args = [
                (path, operation, args.preset, args.threads, args.keep_originals)
                for path in files
            ]
            with mp.Pool(processes=workers) as pool:
                async_results = [
                    pool.apply_async(process_file_worker, (arg,)) for arg in worker_args
                ]
                for i, async_result in enumerate(async_results, 1):
                    result = async_result.get()
                    results.append(result)
                    status = (
                        "🗑️ ✅"
                        if result.success and result.original_deleted
                        else "✅"
                        if result.success
                        else "❌"
                    )
                    print(f"  [{i}/{len(files)}] {result.path.name} - {status}")
        else:
            for i, path in enumerate(files, 1):
                result = process_file_worker(
                    (
                        path,
                        operation,
                        args.preset,
                        args.threads,
                        args.keep_originals,
                    )
                )
                results.append(result)
                status = (
                    "🗑️ ✅"
                    if result.success and result.original_deleted
                    else "✅"
                    if result.success
                    else "❌"
                )
                print(f"  [{i}/{len(files)}] {path.name} - {status}")

    if results:
        if RICH_AVAILABLE:
            print_results_rich(results, directory, operation)
        else:
            print_results_basic(results, directory, operation)


if __name__ == "__main__":
    raise SystemExit(main())
