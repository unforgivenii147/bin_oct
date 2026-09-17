#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import sys
import tarfile
from pathlib import Path

import zstandard as zstd


def split_tar_zst(input_file, num_parts):
    if not os.path.exists(input_file):
        print(f"Error: File '{input_file}' not found.", file=sys.stderr)
        sys.exit(1)
    if num_parts < 1:
        print("Error: N must be at least 1.", file=sys.stderr)
        sys.exit(1)
    base_name = Path(input_file).stem
    base_name = base_name.removesuffix(".tar")
    output_dir = Path(input_file).parent
    print(f"Reading tar.zst file: {input_file}")
    dctx = zstd.ZstdDecompressor()
    with open(input_file, "rb") as f:
        tar_data = dctx.stream_reader(f).read()
    import io

    tar_buffer = io.BytesIO(tar_data)
    tar = tarfile.open(fileobj=tar_buffer, mode="r|")
    members = []
    for member in tar:
        members.append(member)
    tar.close()
    total_members = len(members)
    print(f"Total files/directories in archive: {total_members}")
    if num_parts > total_members:
        print(
            f"Warning: N ({num_parts}) is greater than number of items ({total_members})."
        )
        print("Some parts may be empty.")
        num_parts = total_members
    items_per_part = total_members // num_parts
    remainder = total_members % num_parts
    tar_buffer.seek(0)
    tar = tarfile.open(fileobj=tar_buffer, mode="r|")
    part_num = 1
    current_part_members = 0
    part_buffer = io.BytesIO()
    part_tar = tarfile.open(fileobj=part_buffer, mode="w|")
    items_for_this_part = items_per_part + (1 if part_num <= remainder else 0)
    for _idx, member in enumerate(tar):
        if member.isfile():
            f = tar.extractfile(member)
            part_tar.addfile(member, f)
        else:
            part_tar.addfile(member)
        current_part_members += 1
        if current_part_members >= items_for_this_part and part_num < num_parts:
            part_tar.close()
            part_buffer.seek(0)
            output_file = output_dir / f"{base_name}.part{part_num:02d}.tar.zst"
            print(f"Writing part {part_num}: {output_file}")
            cctx = zstd.ZstdCompressor()
            with open(output_file, "wb") as f:
                f.write(cctx.compress(part_buffer.read()))
            part_num += 1
            current_part_members = 0
            part_buffer = io.BytesIO()
            part_tar = tarfile.open(fileobj=part_buffer, mode="w|")
            items_for_this_part = items_per_part + (1 if part_num <= remainder else 0)
    tar.close()
    part_tar.close()
    part_buffer.seek(0)
    output_file = output_dir / f"{base_name}.part{part_num:02d}.tar.zst"
    print(f"Writing part {part_num}: {output_file}")
    cctx = zstd.ZstdCompressor()
    with open(output_file, "wb") as f:
        f.write(cctx.compress(part_buffer.read()))
    print(f"\nSuccessfully split into {part_num} parts!")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python split_tar_zst.py <input_file> <N>")
        print("  input_file: Path to the tar.zst file to split")
        print("  N: Number of parts to create")
        sys.exit(1)
    input_file = sys.argv[1]
    try:
        num_parts = int(sys.argv[2])
    except ValueError:
        print(f"Error: N must be an integer, got '{sys.argv[2]}'", file=sys.stderr)
        sys.exit(1)
    split_tar_zst(input_file, num_parts)
