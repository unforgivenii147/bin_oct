#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import mmap
import os
import random
import secrets
from pathlib import Path


def enhanced_shuffle(
    input_file, output_file_prefix=None, methods=None, repeats=3
) -> None:
    if methods is None:
        methods = ["basic", "crypto", "shuffle3"]
    input_path = Path(input_file)
    file_size = input_path.stat().st_size
    print(f"Read {file_size} bytes from {input_file}")
    lines = []
    if file_size > 5 * 1024 * 1024:
        print("File size > 5MB, attempting to use mmap.")
        try:
            with Path(input_file).open("r+b") as f:
                mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                decoded_content = mm.decode("utf-8", errors="ignore")
                lines = decoded_content.splitlines(keepends=True)
                mm.close()
        except Exception as e:
            print(f"Error using mmap: {e}. Falling back to standard file reading.")
            with Path(input_file).open(encoding="utf-8") as f:
                lines = f.readlines()
    else:
        with Path(input_file).open(encoding="utf-8") as f:
            lines = f.readlines()
    original_count = len(lines)
    print(f"Read {original_count} lines from {input_file}")
    for method in methods:
        print(f"\n--- Shuffling with method: {method} ---")
        shuffled_lines = lines.copy()
        for _ in range(repeats):
            if method == "basic":
                random.shuffle(shuffled_lines)
            elif method == "crypto":
                crypto_shuffle(shuffled_lines)
            elif method == "shuffle3":
                shuffle3(shuffled_lines)
        output_path = output_file_prefix or input_file
        if output_file_prefix:
            output_path = f"{output_file_prefix}_{method}.txt"
        else:
            base, ext = os.path.splitext(input_file)
            output_path = f"{base}_{method}{ext}"
        with Path(output_path).open("w", encoding="utf-8") as f:
            f.writelines(shuffled_lines)
        print(
            f"Shuffled {original_count} lines using method '{method}' with {repeats} passes"
        )
        print(f"Output written to: {output_path}")


def crypto_shuffle(lst) -> None:
    for i in range(len(lst) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        lst[i], lst[j] = lst[j], lst[i]


def shuffle3(lst) -> None:
    sys_random = random.SystemRandom()
    for i in range(len(lst) - 1, 0, -1):
        j = sys_random.randint(0, i)
        lst[i], lst[j] = lst[j], lst[i]


def test_randomness(input_file) -> None:
    method_to_test = "crypto"
    print(f"Testing randomness with method: {method_to_test}")
    lines_to_test = []
    try:
        with Path(input_file).open(encoding="utf-8") as f:
            lines_to_test = [line.strip() for line in f.readlines()[:100]]
    except Exception as e:
        print(f"Error reading file for testing: {e}")
        return
    if not lines_to_test:
        print("No lines found to test.")
        return
    original_order = lines_to_test.copy()
    for i in range(5):
        current_lines = original_order.copy()
        if method_to_test == "basic":
            random.shuffle(current_lines)
        elif method_to_test == "crypto":
            crypto_shuffle(current_lines)
        elif method_to_test == "shuffle3":
            shuffle3(current_lines)
        changes = sum(
            1 for a, b in zip(original_order, current_lines, strict=False) if a != b
        )
        print(
            f"Shuffle {i + 1}: {changes} out of {len(current_lines)} positions changed"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Randomize lines in a file")
    parser.add_argument("input_file", help="Input file to shuffle")
    parser.add_argument(
        "-o",
        "--output",
        help="Output file prefix (default: will append method name to input file name)",
    )
    parser.add_argument(
        "-r",
        "--repeats",
        type=int,
        default=3,
        help="Number of shuffle passes per method (default: 3)",
    )
    parser.add_argument(
        "-t",
        "--test",
        action="store_true",
        help="Test randomness of the 'crypto' method",
    )
    args = parser.parse_args()
    output_prefix = args.output
    if output_prefix and not output_prefix.endswith((".txt", ".TXT")):
        output_prefix += ".txt"
    if args.test:
        test_randomness(args.input_file)
    else:
        enhanced_shuffle(
            args.input_file,
            output_prefix,
            methods=["basic", "crypto", "shuffle3"],
            repeats=args.repeats,
        )


if __name__ == "__main__":
    raise SystemExit(main())
