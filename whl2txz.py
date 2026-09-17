#!/data/data/com.termux/files/home/.local/bin/python
"""Bidirectional converter between Python wheel (.whl) files and tar.xz archives.

This script converts .whl files to .tar.xz and vice versa, preserving file
metadata such as modification times and permissions. It supports processing
individual files, globs, or directories (optionally recursive), uses a
multiprocessing pool of 8 workers for parallel conversion, and uses loguru
for logging.
"""

from __future__ import annotations

import argparse
import sys
import tarfile
import traceback
import zipfile
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Final

from loguru import logger

# Module-level constants
MAX_WORKERS: Final[int] = 8
DEFAULT_PERMISSION: Final[int] = 0o644
EXECUTABLE_PERMISSION: Final[int] = 0o755
PERMISSION_MASK: Final[int] = 0o7777
UID: Final[int] = 0
GID: Final[int] = 0
UNAME: Final[str] = "root"
GNAME: Final[str] = "root"
EXECUTABLE_EXTENSIONS: Final[tuple[str, ...]] = (".sh", ".py", ".exe")

# Type aliases
ConversionResult = tuple[bool, str, Path | None]
FileResult = tuple[Path, bool, str, Path | None]


def convert_zip_time_to_timestamp(
    date_time: tuple[int, int, int, int, int, int],
) -> float:
    """Convert a ZIP date_time tuple to a UNIX timestamp.

    Args:
        date_time: A 6-tuple of (year, month, day, hour, minute, second).

    Returns:
        The corresponding UNIX timestamp, or the current time on failure.
    """
    try:
        dt = datetime(*date_time)
        return dt.timestamp()
    except (ValueError, TypeError):
        return datetime.now().timestamp()


def get_unique_path(path: Path) -> Path:
    """Return a unique path by appending a numeric suffix if needed.

    Args:
        path: The desired output path.

    Returns:
        A path that does not yet exist on the filesystem.
    """
    if not path.exists():
        return path
    counter = 1
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    while True:
        new_path = parent / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1


def preserve_zip_metadata(
    zip_member: zipfile.ZipInfo, tarinfo: tarfile.TarInfo
) -> tarfile.TarInfo:
    """Copy metadata from a ZIP member onto a TarInfo object.

    Args:
        zip_member: The source ZIP entry.
        tarinfo: The target tar entry to update.

    Returns:
        The updated TarInfo instance.
    """
    tarinfo.size = zip_member.file_size
    if zip_member.date_time:
        tarinfo.mtime = convert_zip_time_to_timestamp(zip_member.date_time)
    if zip_member.external_attr:
        unix_permissions = zip_member.external_attr >> 16 & PERMISSION_MASK
        if unix_permissions:
            tarinfo.mode = unix_permissions
        else:
            tarinfo.mode = (
                EXECUTABLE_PERMISSION
                if zip_member.filename.endswith(EXECUTABLE_EXTENSIONS)
                else DEFAULT_PERMISSION
            )
    else:
        tarinfo.mode = DEFAULT_PERMISSION
    tarinfo.type = tarfile.REGTYPE
    tarinfo.uid = UID
    tarinfo.gid = GID
    tarinfo.uname = UNAME
    tarinfo.gname = GNAME
    return tarinfo


def preserve_tar_metadata(
    tarinfo: tarfile.TarInfo, zipinfo: zipfile.ZipInfo
) -> zipfile.ZipInfo:
    """Copy metadata from a TarInfo object onto a ZipInfo object.

    Args:
        tarinfo: The source tar entry.
        zipinfo: The target ZIP entry to update.

    Returns:
        The updated ZipInfo instance.
    """
    if hasattr(tarinfo, "mtime") and tarinfo.mtime:
        dt = datetime.fromtimestamp(tarinfo.mtime)
        zipinfo.date_time = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    if hasattr(tarinfo, "mode") and tarinfo.mode:
        zipinfo.external_attr = (tarinfo.mode & 0xFFFF) << 16
    return zipinfo


def convert_whl_to_tarxz(path: Path, remove_original: bool = False) -> ConversionResult:
    """Convert a wheel (.whl) file to a tar.xz archive.

    Args:
        path: Path to the input .whl file.
        remove_original: If True, delete the source file on success.

    Returns:
        A tuple of (success, message, output_path).
    """
    try:
        if not path.exists() or not path.is_file():
            return False, f"Invalid file: {path}", None
        if path.suffix.lower() != ".whl":
            return False, f"Not a wheel file: {path.name}", None
        output_path = path.with_suffix(".tar.xz")
        if output_path.exists():
            output_path = get_unique_path(output_path)
            print(f"Target exists, using: {output_path.name}")
        converted_count = 0
        failed_members: list[str] = []
        with zipfile.ZipFile(path, "r") as zip_file:
            bad_file = zip_file.testzip()
            if bad_file:
                return False, f"Corrupt ZIP file: {bad_file}", None
            with tarfile.open(output_path, "w:xz") as tar_file:
                for member in zip_file.infolist():
                    if member.is_dir():
                        continue
                    try:
                        with zip_file.open(member) as source:
                            tarinfo = tarfile.TarInfo(name=member.filename)
                            tarinfo = preserve_zip_metadata(member, tarinfo)
                            tar_file.addfile(tarinfo, source)
                            converted_count += 1
                    except Exception as e:
                        failed_members.append(f"{member.filename}: {e}")
        if failed_members:
            logger.warning(
                f"Failed to convert {len(failed_members)} files in {path.name}"
            )
        if output_path.exists() and output_path.stat().st_size > 0:
            if remove_original:
                try:
                    path.unlink()
                    print(f"Removed original: {path.name}")
                except Exception as e:
                    logger.error(f"Failed to remove original file {path.name}: {e}")
                    return (
                        False,
                        f"Conversion succeeded but failed to remove original: {e}",
                        output_path,
                    )
            return (True, f"Converted {converted_count} files to tar.xz", output_path)
        else:
            return False, "Output file is empty or missing", None
    except Exception as e:
        return False, f"Conversion error: {e}", None


def convert_tarxz_to_whl(path: Path, remove_original: bool = False) -> ConversionResult:
    """Convert a tar.xz archive to a wheel (.whl) file.

    Args:
        path: Path to the input .tar.xz file.
        remove_original: If True, delete the source file on success.

    Returns:
        A tuple of (success, message, output_path).
    """
    try:
        if not path.exists() or not path.is_file():
            return False, f"Invalid file: {path}", None
        if not (path.suffix == ".xz" and path.stem.endswith(".tar")):
            return False, f"Not a tar.xz file: {path.name}", None
        stem = path.stem
        stem = stem.removesuffix(".tar")
        output_path = path.parent / f"{stem}.whl"
        if output_path.exists():
            output_path = get_unique_path(output_path)
            print(f"Target exists, using: {output_path.name}")
        converted_count = 0
        with (
            tarfile.open(path, "r:xz") as tar_file,
            zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zip_file,
        ):
            for member in tar_file.getmembers():
                if member.isdir():
                    continue
                try:
                    file_content = tar_file.extractfile(member)
                    if file_content:
                        zipinfo = zipfile.ZipInfo(filename=member.name)
                        zipinfo = preserve_tar_metadata(member, zipinfo)
                        zipinfo.file_size = member.size
                        zip_file.writestr(zipinfo, file_content.read())
                        converted_count += 1
                        file_content.close()
                except Exception as e:
                    logger.error(f"Failed to convert {member.name}: {e}")
                    return (
                        False,
                        f"Failed to convert member {member.name}: {e}",
                        None,
                    )
        if output_path.exists() and output_path.stat().st_size > 0:
            try:
                with zipfile.ZipFile(output_path, "r") as test_zip:
                    bad_file = test_zip.testzip()
                    if bad_file:
                        return (False, f"Created corrupt zip file: {bad_file}", None)
            except Exception as e:
                return False, f"Verification failed: {e}", None
            if remove_original:
                try:
                    path.unlink()
                    print(f"Removed original: {path.name}")
                except Exception as e:
                    logger.error(f"Failed to remove original file {path.name}: {e}")
                    return (
                        False,
                        f"Conversion succeeded but failed to remove original: {e}",
                        output_path,
                    )
            return (True, f"Converted {converted_count} files to wheel", output_path)
        else:
            return False, "Output file is empty or missing", None
    except tarfile.TarError as e:
        return False, f"Tar error: {e}", None
    except Exception as e:
        return False, f"Conversion error: {e}", None


def process_file(path: Path, remove_original: bool = False) -> ConversionResult:
    """Dispatch conversion based on the file type.

    Args:
        path: Path to the file to convert.
        remove_original: If True, delete the source file on success.

    Returns:
        A tuple of (success, message, output_path).
    """
    path = Path(path)
    if not path.exists():
        return False, f"File not found: {path}", None
    if path.suffix.lower() == ".whl":
        print(f"Converting wheel to tar.xz: {path.name}")
        return convert_whl_to_tarxz(path, remove_original)
    elif path.suffix == ".xz" and (path.stem.endswith(".tar") or ".tar." in str(path)):
        print(f"Converting tar.xz to wheel: {path.name}")
        return convert_tarxz_to_whl(path, remove_original)
    else:
        return (
            False,
            f"Unsupported file type: {path.suffix} (only .whl or .tar.xz)",
            None,
        )


def find_convertible_files(directory: Path, recursive: bool = False) -> list[Path]:
    """Find .whl and .tar.xz files inside a directory.

    Args:
        directory: Directory to search.
        recursive: Whether to search subdirectories.

    Returns:
        A list of matching file paths.
    """
    if not directory.exists() or not directory.is_dir():
        return []
    convertible_files: list[Path] = []
    whl_pattern = "**/*.whl" if recursive else "*.whl"
    convertible_files.extend(directory.glob(whl_pattern))
    tarxz_pattern = "**/*.tar.xz" if recursive else "*.tar.xz"
    convertible_files.extend(directory.glob(tarxz_pattern))
    return convertible_files


def process_single_file(args: tuple[Path, bool]) -> FileResult:
    """Worker entry point for converting a single file in a pool.

    Args:
        args: A tuple of (path, remove_original).

    Returns:
        A tuple of (path, success, message, output_path).
    """
    path, remove_original = args
    success, message, output_path = process_file(path, remove_original)
    return path, success, message, output_path


def build_arg_parser() -> argparse.ArgumentParser:
    """Build and return the command-line argument parser.

    Returns:
        The configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        description="Bidirectional converter between .whl and .tar.xz files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s package.whl
  %(prog)s package.tar.xz
  %(prog)s *.whl
  %(prog)s /path/to/dir
  %(prog)s --recursive
  %(prog)s --remove-original
        """,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument(
        "-r", "--recursive", action="store_true", help="Search directories recursively"
    )
    parser.add_argument(
        "--remove-original",
        action="store_true",
        help="Remove original files after successful conversion",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress non-error output"
    )
    return parser


def configure_logging(verbose: bool, quiet: bool) -> None:
    """Configure the loguru logger based on CLI verbosity flags.

    Args:
        verbose: Enable debug-level logging.
        quiet: Restrict logging to errors only.
    """
    logger.remove()
    if quiet:
        level = "ERROR"
    elif verbose:
        level = "DEBUG"
    else:
        level = "INFO"
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> - "
            "<level>{level}</level> - <level>{message}</level>"
        ),
    )


def collect_convertible_files(paths: list[str], recursive: bool) -> list[Path]:
    """Gather all convertible files from the given input paths.

    Args:
        paths: List of file or directory path strings.
        recursive: Whether to search directories recursively.

    Returns:
        A list of convertible file paths.
    """
    convertible_files: list[Path] = []
    for input_path in paths:
        path = Path(input_path)
        if not path.exists():
            logger.error(f"Path does not exist: {path}")
            continue
        if path.is_file():
            if path.suffix.lower() == ".whl" or (
                path.suffix == ".xz" and ".tar" in str(path)
            ):
                convertible_files.append(path)
            else:
                logger.warning(f"Skipping unsupported file: {path}")
        elif path.is_dir():
            found = find_convertible_files(path, recursive)
            convertible_files.extend(found)
            print(f"Found {len(found)} convertible files in {path}")
        else:
            logger.error(f"Invalid path: {path}")
    return convertible_files


def run_conversions(
    convertible_files: list[Path], remove_original: bool
) -> list[FileResult]:
    """Run conversions either sequentially or via a multiprocessing pool.

    Args:
        convertible_files: Files to convert.
        remove_original: Whether to delete originals on success.

    Returns:
        A list of per-file result tuples.
    """
    results: list[FileResult] = []
    if len(convertible_files) == 1:
        success, message, output_path = process_file(
            convertible_files[0], remove_original
        )
        results.append((convertible_files[0], success, message, output_path))
        return results

    file_args = [(f, remove_original) for f in convertible_files]
    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[tuple[Path, Any]] = [
            (file_arg[0], pool.apply_async(process_single_file, (file_arg,)))
            for file_arg in file_args
        ]
        for path, async_result in async_results:
            try:
                results.append(async_result.get())
            except Exception as e:
                results.append((path, False, f"Execution failed: {e}", None))
                logger.error(f"Failed to process {path.name}: {e}")
    return results


def print_results(
    results: list[FileResult], remove_original: bool, verbose: bool
) -> int:
    """Print a summary of conversion results.

    Args:
        results: The per-file result tuples.
        remove_original: Whether originals were removed.
        verbose: Whether to include detailed messages.

    Returns:
        The process exit code (0 on full success, 1 otherwise).
    """
    success_count = 0
    failure_count = 0
    output_lines: list[str] = []
    output_lines.append("")
    output_lines.append("=" * 40)
    output_lines.append("CONVERSION RESULTS")
    output_lines.append("-" * 40)

    for path, success, message, output_path in results:
        if success:
            success_count += 1
            status = "✓ OK"
            input_type = "whl" if path.suffix == ".whl" else "tar.xz"
            output_type = (
                "tar.xz" if output_path and output_path.suffix == ".xz" else "whl"
            )
            size_info = ""
            if output_path and output_path.exists():
                size_kb = output_path.stat().st_size / 1024
                size_info = f" ({size_kb:.1f} KB)"
            output_lines.append(
                f"{status} {path.name} [{input_type}] → "
                f"{output_path.name if output_path else 'unknown'} "
                f"[{output_type}]{size_info}"
            )
            if verbose:
                output_lines.append(f"   {message}")
        else:
            failure_count += 1
            status = "✗ FAIL"
            output_lines.append(f"{status} {path.name}: {message}")

    output_lines.append("-" * 40)
    output_lines.append(f"Summary: {success_count} successful, {failure_count} failed")
    if remove_original and success_count > 0:
        output_lines.append("✓ Original files were removed after successful conversion")

    print("\n".join(output_lines))
    return 0 if failure_count == 0 else 1


def main() -> int:
    """Entry point for the CLI.

    Returns:
        Process exit code.
    """
    parser = build_arg_parser()
    args = parser.parse_args()

    configure_logging(args.verbose, args.quiet)

    convertible_files = collect_convertible_files(args.paths, args.recursive)

    if not convertible_files:
        if args.paths == ["."]:
            print("No .whl or .tar.xz files found in current directory")
        else:
            logger.error("No convertible files found")
        return 1

    print(f"Processing {len(convertible_files)} file(s)")
    if args.remove_original:
        print("Original files will be removed after successful conversion")

    results = run_conversions(convertible_files, args.remove_original)
    return print_results(results, args.remove_original, args.verbose)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Fatal error: {e}\n{traceback.format_exc()}")
        sys.exit(1)
