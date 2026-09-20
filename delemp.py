#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations
import argparse
import mmap
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from dh import is_binary, fsz

MMAP_THRESHOLD = 1024 * 1024
BOLD = "\x1b[1m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
CYAN = "\x1b[36m"
RED = "\x1b[31m"
RESET = "\x1b[0m"
DIM = "\x1b[2m"
BINARY_SIGNATURES = (
    b"\x00",
    b"\xff\xd8\xff",
    b"\x89PNG",
    b"GIF8",
    b"BM",
    b"\x00\x00\x01\x00",
    b"PK\x03\x04",
    b"\x1f\x8b",
    b"\x7fELF",
    b"MZ",
    b"\xca\xfe\xba\xbe",
    b"%PDF",
    b"\xd0\xcf\x11\xe0",
    b"SQLite format 3",
    b"RIFF",
    b"\x1aE\xdf\xa3",
    b"\x00\x00\x00\x18ftyp",
    b"\x00\x00\x00\x1cftyp",
    b"ID3",
    b"OggS",
    b"fLaC",
    b"FWS",
    b"CWS",
    b"%!PS",
    b"\x1f\x9d",
    b"\x1f\xa0",
    b"BZh",
    b"\xfd7zXZ\x00",
    b"7z\xbc\xaf'\x1c",
    b"Rar!\x1a\x07",
    b"\xed\xab\xee\xdb",
    b"\xd4\xc3\xb2\xa1",
    b"\xa1\xb2\xc3\xd4",
)
_TEXT_CHARS = bytearray(
    {7, 8, 9, 10, 12, 13, 27} | set(range(32, 127)) | set(range(128, 256))
)
_BINARY_CHECK_SIZE = 8192


def remove_all_blank_lines(text: str) -> str:
    lines = text.splitlines(keepends=True)
    return "".join(line for line in lines if line.strip() != "")


def preserve_single_blank_lines(text: str) -> str:
    lines = text.splitlines(keepends=True)
    result_lines = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        result_lines.append(line)
        prev_blank = is_blank
    while len(result_lines) > 1 and result_lines[-1].strip() == "":
        result_lines.pop()
    return "".join(result_lines)


def process_small_file(
    file_path: Path, preserve_single: bool, remove_spaces: bool
) -> tuple[str, int, int, str]:
    content = file_path.read_text(encoding="utf-8")
    total_lines = len(content.splitlines())
    if preserve_single:
        result = preserve_single_blank_lines(content)
    else:
        result = remove_all_blank_lines(content)
    result_lines = len(result.splitlines()) if result else 0
    removed_lines = total_lines - result_lines
    if removed_lines > 0:
        file_path.write_text(result, encoding="utf-8")
    return (str(file_path), total_lines, removed_lines, "processed")


def process_large_file_mmap(
    file_path: Path, preserve_single: bool, remove_spaces: bool
) -> tuple[str, int, int, str]:
    try:
        with open(file_path, "r+b") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                content = mm.read().decode("utf-8", errors="ignore")
            total_lines = len(content.splitlines())
            if preserve_single:
                result = preserve_single_blank_lines(content)
            else:
                result = remove_all_blank_lines(content)
            result_lines = len(result.splitlines()) if result else 0
            removed_lines = total_lines - result_lines
            if removed_lines > 0:
                f.seek(0)
                f.write(result.encode("utf-8"))
                f.truncate()
        return (str(file_path), total_lines, removed_lines, "processed")
    except Exception as e:
        return (str(file_path), 0, 0, f"Error with mmap: {e!s}")


def remove_blank_lines(
    file_path: Path, preserve_single: bool = False, remove_spaces: bool = False
) -> tuple[str, int, int, str]:
    try:
        file_size = file_path.stat().st_size
        if file_size > MMAP_THRESHOLD:
            return process_large_file_mmap(file_path, preserve_single, remove_spaces)
        else:
            return process_small_file(file_path, preserve_single, remove_spaces)
    except Exception as e:
        return (str(file_path), 0, 0, f"Error: {e!s}")


def process_file(args: tuple[Path, Path, bool, bool]) -> tuple[str, int, int, str]:
    base_dir, file_path, preserve_single, remove_spaces = args
    if is_binary(file_path):
        try:
            rel_path = file_path.relative_to(base_dir)
            return (str(rel_path), 0, 0, "binary")
        except ValueError:
            return (str(file_path), 0, 0, "binary")
    result = remove_blank_lines(file_path, preserve_single, remove_spaces)
    try:
        rel_path = Path(result[0]).relative_to(base_dir)
        file_size = file_path.stat().st_size
        method = " [mmap]" if file_size > MMAP_THRESHOLD else ""
        status = result[3] + method if result[3] == "processed" else result[3]
        return (str(rel_path), result[1], result[2], status)
    except ValueError:
        return result


def collect_files(paths: list[Path]) -> list[tuple[Path, Path]]:
    files = []
    for path in paths:
        if not path.exists():
            print(f"{YELLOW}⚠ Warning:{RESET} '{path}' does not exist, skipping.")
            continue
        if path.is_file():
            if not path.is_symlink():
                files.append((path.parent, path))
        elif path.is_dir():
            for file_path in path.rglob("*"):
                if (
                    file_path.is_file()
                    and not file_path.is_symlink()
                    and ".git" not in file_path.parts
                ):
                    files.append((path, file_path))
        else:
            print(
                f"{YELLOW}⚠ Warning:{RESET} '{path}' is not a file or directory, skipping."
            )
    return files


def print_header(
    paths: list[Path], preserve_single: bool, remove_spaces: bool, mmap_threshold: int
):
    print(f"\n{BOLD}{CYAN}╔{'═' * 40}╗{RESET}")
    print(
        f"{BOLD}{CYAN}║{RESET}         {BOLD}Blank Line Remover{RESET}                    {BOLD}{CYAN}║{RESET}"
    )
    print(f"{BOLD}{CYAN}╚{'═' * 40}╝{RESET}")
    print(f"{BOLD}Processing paths:{RESET}")
    for path in paths:
        path_type = "📄" if path.is_file() else "📁"
        print(f"  {path_type} {path.absolute()}")
    print(f"\n{BOLD}Mode:{RESET} ", end="")
    if preserve_single:
        print(f"{CYAN}Preserve single blank lines{RESET}", end="")
    else:
        print(f"{GREEN}Remove all blank lines{RESET}", end="")
    if remove_spaces:
        print(f" {YELLOW}(+ whitespace-only lines){RESET}")
    else:
        print()


def print_results(
    results: list[tuple],
    total_removed: int,
    total_files: int,
    show_all_binary: bool = False,
    mmap_threshold: int = MMAP_THRESHOLD,
):
    print(f"\n{BOLD}{CYAN}{'─' * 42}{RESET}\n")
    results.sort(key=lambda x: x[0])
    processed = [(p, t, r, s) for p, t, r, s in results if s.startswith("processed")]
    skipped_binary = [(p, t, r, s) for p, t, r, s in results if s == "binary"]
    errors = [
        (p, t, r, s)
        for p, t, r, s in results
        if s not in ("processed", "binary") and not s.startswith("processed")
    ]
    large_files_count = sum(1 for _, _, _, s in processed if "[mmap]" in s)
    if processed:
        print(f"{BOLD}{GREEN}✓ Modified files:{RESET}\n")
        for path, total_lines, removed, status in processed:
            if removed > 0:
                method_indicator = f" {DIM}[mmap]{RESET}" if "[mmap]" in status else ""
                print(f"  {GREEN}●{RESET} {path}{method_indicator}")
                print(
                    f"    {DIM}Lines: {total_lines:,}  →  Removed: {GREEN}{removed:,}{RESET}"
                )
            else:
                print(f"  {DIM}○{RESET} {path} {DIM}(no blank lines found){RESET}")
        print()
    if skipped_binary:
        print(f"{BOLD}{YELLOW}⊘ Skipped binary files: {len(skipped_binary)}{RESET}")
        display_count = (
            len(skipped_binary) if show_all_binary else min(5, len(skipped_binary))
        )
        for path, _, _, _ in skipped_binary[:display_count]:
            print(f"  {YELLOW}⊘{RESET} {path}")
        if len(skipped_binary) > display_count:
            print(
                f"  {DIM}... and {len(skipped_binary) - display_count} more binary files{RESET}"
            )
        print()
    if errors:
        print(f"{BOLD}{RED}✗ Errors:{RESET}\n")
        for path, _, _, status in errors:
            print(f"  {RED}✗{RESET} {path}")
            print(f"    {DIM}{status}{RESET}")
        print()
    print(f"{BOLD}{CYAN}{'─' * 42}{RESET}")
    print(f"{BOLD}Summary:{RESET}")
    print(f"  Total files found:     {BOLD}{total_files:,}{RESET}")
    print(f"  Text files processed:  {BOLD}{len(processed):,}{RESET}")
    if large_files_count > 0:
        print(f"    Large files (mmap):  {BOLD}{large_files_count:,}{RESET}")
    print(f"  Binary files skipped:  {BOLD}{YELLOW}{len(skipped_binary):,}{RESET}")
    print(
        f"  Files modified:        {BOLD}{sum(1 for r in processed if r[2] > 0):,}{RESET}"
    )
    print(f"  Lines removed:         {BOLD}{GREEN}{total_removed:,}{RESET}")
    if errors:
        print(f"  Errors:                {BOLD}{RED}{len(errors):,}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 42}{RESET}\n")


def main():
    global MMAP_THRESHOLD
    parser = argparse.ArgumentParser(
        description="Remove blank lines from files recursively using parallel processing (with mmap support)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files and/or directories to process (default: current directory)",
    )
    parser.add_argument(
        "-1",
        dest="preserve_single",
        action="store_true",
        help="Preserve single blank lines (remove only multiple consecutive blank lines)",
    )
    parser.add_argument(
        "-s",
        "--space",
        action="store_true",
        help="Also remove lines that contain only whitespace characters",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=None,
        help="Number of worker processes (default: CPU count)",
    )
    parser.add_argument(
        "-t",
        "--threshold",
        type=int,
        default=MMAP_THRESHOLD,
        help=f"File size threshold for using mmap in bytes (default: {MMAP_THRESHOLD:,} = 1MB)",
    )
    parser.add_argument(
        "-b",
        "--show-binary",
        action="store_true",
        help="Show all skipped binary files (default: shows only first 5)",
    )
    args = parser.parse_args()
    MMAP_THRESHOLD = args.threshold
    paths = [Path(p).resolve() for p in args.paths]
    print_header(paths, args.preserve_single, args.space, MMAP_THRESHOLD)
    print(f"{BOLD}Scanning for files...{RESET}", end=" ", flush=True)
    file_list = collect_files(paths)
    total_files = len(file_list)
    print(f"{GREEN}Done!{RESET} Found {BOLD}{total_files:,}{RESET} files.\n")
    if not file_list:
        print(f"{YELLOW}No files found to process.{RESET}")
        return
    process_args = [
        (base_dir, file_path, args.preserve_single, args.space)
        for base_dir, file_path in file_list
    ]
    max_workers = args.workers or min(32, (os.cpu_count() or 1) + 4)
    results = []
    total_removed = 0
    processed_count = 0
    skipped_count = 0
    error_count = 0
    large_count = 0
    print(f"{BOLD}Processing files...{RESET}")
    print(
        f"{DIM}(Using {max_workers} worker processes, mmap for files > {fsz(MMAP_THRESHOLD)}){RESET}\n"
    )
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {
            executor.submit(process_file, arg): arg[1] for arg in process_args
        }
        completed = 0
        for future in as_completed(future_to_file):
            completed += 1
            try:
                result = future.result()
                _, _, removed, status = result
                total_removed += removed
                results.append(result)
                if status.startswith("processed"):
                    processed_count += 1
                    if "[mmap]" in status:
                        large_count += 1
                elif status == "binary":
                    skipped_count += 1
                else:
                    error_count += 1
            except Exception as e:
                error_count += 1
                results.append((str(future_to_file[future]), 0, 0, f"error: {e}"))
            binary_info = (
                f" {YELLOW}({skipped_count} binary){RESET}" if skipped_count > 0 else ""
            )
            large_info = (
                f" {CYAN}({large_count} mmap){RESET}" if large_count > 0 else ""
            )
            error_info = (
                f" {RED}({error_count} errors){RESET}" if error_count > 0 else ""
            )
            print(
                f"\r  Progress: {completed:,}/{total_files:,} files processed{binary_info}{large_info}{error_info}",
                end="",
                flush=True,
            )
    print(
        f"\r  Progress: {GREEN}Complete!{RESET} "
        f"{DIM}({processed_count:,} text"
        + (f", {large_count:,} mmap" if large_count > 0 else "")
        + f", {skipped_count:,} binary, {error_count:,} errors){RESET}"
        + " " * 20
    )
    print_results(results, total_removed, total_files, args.show_binary, MMAP_THRESHOLD)


if __name__ == "__main__":
    raise SystemExit(main())
