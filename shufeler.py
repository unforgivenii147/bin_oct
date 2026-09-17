#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import mmap
import random
import secrets
import sys
from pathlib import Path

MMAP_THRESHOLD_BYTES = 1 * 1024 * 1024


def get_line_offsets(path: Path):
    offsets = []
    with (
        path.open("rb") as f,
        mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm,
    ):
        offset = 0
        while True:
            offsets.append(offset)
            newline_pos = mm.find(b"\n", offset)
            if newline_pos == -1:
                break
            offset = newline_pos + 1
    return offsets


def crypto_shuffle_offsets(offsets) -> None:
    n = len(offsets)
    for i in range(n - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        offsets[i], offsets[j] = offsets[j], offsets[i]


def shuffle3_offsets(offsets) -> None:
    sys_random = random.SystemRandom()
    n = len(offsets)
    for i in range(n - 1, 0, -1):
        j = sys_random.randint(0, i)
        offsets[i], offsets[j] = offsets[j], offsets[i]


def weighted_shuffle_offsets(offsets) -> None:
    n = len(offsets)
    for i in range(n - 1, 0, -1):
        j = random.randint(0, i)
        offsets[i], offsets[j] = offsets[j], offsets[i]
    if n > 1:
        for i in range(n - 1):
            swap_pos = random.randint(i + 1, n - 1)
            offsets[i], offsets[swap_pos] = offsets[swap_pos], offsets[i]


def enhanced_shuffle_large_file(input_path: Path, output_path: Path) -> bool:
    input_path = Path(input_path)
    output_path = Path(output_path)
    if not input_path.exists():
        print(f"Error: Input file '{input_path}' not found.", file=sys.stderr)
        return False
    file_size = input_path.stat().st_size
    print(f"Input file size: {file_size / (1024 * 1024):.2f} MB")
    print("Reading line offsets...")
    line_offsets = get_line_offsets(input_path)
    original_line_count = len(line_offsets)
    print(f"Found {original_line_count} lines.")
    if original_line_count == 0:
        print("Input file is empty. Exiting.")
        output_path.touch()
        return True
    print("Shuffling line offsets...")
    crypto_shuffle_offsets(line_offsets)
    shuffle3_offsets(line_offsets)
    weighted_shuffle_offsets(line_offsets)
    random.shuffle(line_offsets)
    print("Writing shuffled lines to output file...")
    try:
        with (
            input_path.open("rb") as infile,
            mmap.mmap(infile.fileno(), 0, access=mmap.ACCESS_READ) as mm,
            output_path.open("wb") as outfile,
        ):
            for i, offset in enumerate(line_offsets):
                next_offset_idx = (
                    line_offsets.index(offset) + 1 if offset in line_offsets else -1
                )
                if next_offset_idx < len(line_offsets):
                    end_of_line_offset = line_offsets[next_offset_idx] - 1
                    if end_of_line_offset < offset:
                        end_of_line_offset = file_size
                else:
                    end_of_line_offset = file_size
                actual_end_of_line = mm.find(b"\n", offset)
                line_data = (
                    mm[offset:file_size]
                    if actual_end_of_line == -1
                    else mm[offset : actual_end_of_line + 1]
                )
                outfile.write(line_data)
                if (i + 1) % 100000 == 0:
                    print(f"  {i + 1}/{original_line_count} lines written...", end="\r")
        return True
    except Exception as e:
        print(f"\nError writing output file: {e}", file=sys.stderr)
        if output_path.exists():
            output_path.unlink()
        return False


def enhanced_shuffle_small_file(input_path: Path, output_path: Path) -> bool:
    input_path = Path(input_path)
    output_path = Path(output_path)
    if not input_path.exists():
        print(f"Error: Input file '{input_path}' not found.", file=sys.stderr)
        return False
    print(f"Reading all lines from {input_path} into memory...")
    try:
        with input_path.open(encoding="utf-8") as f:
            lines = f.readlines()
    except MemoryError:
        print(
            f"MemoryError: File '{
                input_path
            }' is too large to load into memory. Consider increasing 1mb or using a system with more RAM.",
            file=sys.stderr,
        )
        return False
    except Exception as e:
        print(f"Error reading input file: {e}", file=sys.stderr)
        return False
    original_count = len(lines)
    if original_count == 0:
        print("Input file is empty. Exiting.")
        output_path.touch()
        return True
    print(f"Read {original_count} lines. Shuffling lines...")
    random.shuffle(lines)
    crypto_shuffle(lines)
    shuffle3(lines)
    weighted_shuffle(lines)
    print(f"Writing shuffled lines to: {output_path}")
    try:
        with output_path.open("w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except Exception as e:
        print(f"Error writing output file: {e}", file=sys.stderr)
        return False


def crypto_shuffle(lst: list[str]) -> None:
    n = len(lst)
    for i in range(n - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        lst[i], lst[j] = lst[j], lst[i]


def shuffle3(lst: list[str]) -> None:
    sys_random = random.SystemRandom()
    n = len(lst)
    for i in range(n - 1, 0, -1):
        j = sys_random.randint(0, i)
        lst[i], lst[j] = lst[j], lst[i]


def weighted_shuffle(lst: list[str]) -> None:
    n = len(lst)
    for i in range(n - 1, 0, -1):
        j = random.randint(0, i)
        lst[i], lst[j] = lst[j], lst[i]
    if n > 1:
        for i in range(n - 1):
            swap_pos = random.randint(i + 1, n - 1)
            lst[i], lst[swap_pos] = lst[swap_pos], lst[i]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Randomize lines in a file, optimized for large files."
    )
    parser.add_argument("input_file", help="Input file to shuffle")
    args = parser.parse_args()
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"Error: Input file '{input_path}' not found.", file=sys.stderr)
        sys.exit(1)
    file_size = input_path.stat().st_size
    output_path = input_path
    success = False
    if file_size > MMAP_THRESHOLD_BYTES:
        print(
            f"File size ({file_size / (1024 * 1024):.2f} MB) exceeds {1} MB. Using mmap strategy."
        )
        success = enhanced_shuffle_large_file(input_path, output_path)
    else:
        N = secrets.randbelow(10)
        print(f"will run {N} times")
        for _i in range(N):
            success = enhanced_shuffle_small_file(input_path, output_path)
            if not success:
                sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
