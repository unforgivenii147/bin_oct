#!/data/data/com.termux/files/home/.local/bin/python
"""
find_elf64.py - Recursively detect 64-bit ELF binaries.

Features:
  * Uses pyelftools for robust ELF parsing.
  * Uses binaryornot to quickly skip text files.
  * Uses pathlib for filesystem operations.
  * Parallel scan via multiprocessing.Pool.imap_unordered (8 workers).
  * Optional -r flag to remove found files (executed in main process).

Usage:
  python3 find_elf64.py [directory] [-r|--remove]

"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
from pathlib import Path
from typing import Iterator

from dh import is_binary

from elftools.elf.elffile import ELFFile
from elftools.common.exceptions import ELFError

WORKERS = 8

ELF_TYPES = {
    "ET_NONE": "no file type",
    "ET_REL": "relocatable object",
    "ET_EXEC": "executable",
    "ET_DYN": "shared object / PIE",
    "ET_CORE": "core dump",
}

ELF_MACHINES = {
    "EM_386": "x86",
    "EM_X86_64": "x86-64",
    "EM_ARM": "ARM",
    "EM_AARCH64": "AArch64",
    "EM_RISCV": "RISC-V",
    "EM_MIPS": "MIPS",
    "EM_PPC": "PowerPC",
    "EM_PPC64": "PowerPC64",
    "EM_S390": "S/390",
    "EM_IA_64": "IA-64",
}


def analyze_file(path: Path) -> dict | None:
    """
    Inspect a single file and return a metadata dict if it is a 64-bit ELF,
    or None otherwise.

    This function is the unit of work dispatched to the multiprocessing pool,
    so it must be a top-level, picklable function. It takes and returns only
    picklable data (Path, dict, None).

    Two-stage filter:
      1. binaryornot -> cheap text-file rejection (no file open cost beyond
         a small header read).
      2. pyelftools  -> authoritative ELF class check + metadata extraction.

    Returns a dict with keys: path, size, type, machine, endianness, entry.
    """

    try:
        if not is_binary(str(path)):
            return None
    except (OSError, PermissionError):
        return None

    try:
        with path.open("rb") as f:
            elf = ELFFile(f)

            if elf.elfclass != 64:
                return None

            info = {
                "path": str(path),
                "size": path.stat().st_size,
                "type": ELF_TYPES.get(elf.header["e_type"], elf.header["e_type"]),
                "machine": ELF_MACHINES.get(
                    elf.header["e_machine"], elf.header["e_machine"]
                ),
                "endianness": "little" if elf.little_endian else "big",
                "entry": f"0x{elf.header['e_entry']:x}",
            }
            return info
    except (ELFError, OSError, PermissionError, KeyError):
        return None


def iter_files(root: Path, follow_symlinks: bool = False) -> Iterator[Path]:
    """
    Yield every regular file under `root`, recursively.

    Uses pathlib's rglob() for a clean recursive walk. Symlinks are skipped
    by default to avoid cycles and double-counting.

    Note: the traversal itself runs in the main process. Only the per-file
    analysis is parallelized. This keeps directory I/O serialized (which the
    OS handles best) while CPU/IO work on file contents is spread across
    workers.
    """
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.is_symlink() and not follow_symlinks:
            continue
        yield path


def scan(root: Path, follow_symlinks: bool = False) -> Iterator[dict]:
    """
    Recursively scan `root` and yield metadata dicts for 64-bit ELF files.

    Uses multiprocessing.Pool with a FIXED number of workers (WORKERS) and
    imap_unordered so results stream back as soon as each file finishes,
    without waiting for earlier files to complete.

    imap_unordered is preferred over imap / map here because:
      * Files take wildly different times to analyze (a large .so is much
        slower than a tiny shell script).
      * We don't care about ordering.
      * It gives the lowest latency from "worker finishes" to "user sees it".
    """
    paths = iter_files(root, follow_symlinks=follow_symlinks)

    with mp.Pool(processes=WORKERS) as pool:
        for result in pool.imap_unordered(analyze_file, paths, chunksize=1):
            if result is not None:
                yield result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recursively find 64-bit ELF binaries.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        type=Path,
        help="directory to scan",
    )
    parser.add_argument(
        "-r",
        "--remove",
        action="store_true",
        help="delete each 64-bit ELF binary that is found",
    )
    parser.add_argument(
        "-L",
        "--follow-symlinks",
        action="store_true",
        help="follow symlinks during traversal",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    root: Path = args.directory.resolve()
    if not root.is_dir():
        return 1

    count = 0
    try:
        for info in scan(root, follow_symlinks=args.follow_symlinks):
            count += 1
            path = Path(info["path"])

            try:
                display = path.relative_to(root)
            except ValueError:
                display = path

            print(f"[{count}] {display}")
            print(f"    Path:       {path}")
            print(f"    Size:       {info['size']:,} bytes")
            print(f"    Type:       {info['type']}")
            print(f"    Machine:    {info['machine']}")
            print(f"    Endianness: {info['endianness']}")
            print(f"    Entry:      {info['entry']}")

            if args.remove:
                try:
                    path.unlink()
                    print("    -> Removed")
                except OSError as e:
                    print(f"    -> Failed to remove: {e}", file=sys.stderr)

            print()
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        return 130
    if count:
        print(f"Found {count} 64-bit ELF binary/binaries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
