#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import re
from multiprocessing import Pool, cpu_count
from pathlib import Path

TARGET_CHUNK_SIZE = 4900
BUFFER_SIZE = 500
MAX_CHUNK_SIZE = 4999


def find_chunk_boundary(
    text: str, start_pos: int, target_size: int = TARGET_32768
) -> int:
    end_pos = min(start_pos + target_size, len(text))
    if end_pos >= len(text):
        return len(text)
    search_start = max(start_pos, end_pos - BUFFER_SIZE)
    search_text = text[search_start : end_pos + BUFFER_SIZE]
    sentence_pattern = r"[.!?]\s+"
    matches = list(re.finditer(sentence_pattern, search_text))
    if matches:
        for match in reversed(matches):
            absolute_pos = search_start + match.end()
            if (
                absolute_pos <= end_pos + BUFFER_SIZE
                and absolute_pos > end_pos - BUFFER_SIZE
            ):
                return absolute_pos
    for i in range(end_pos, max(start_pos, end_pos - BUFFER_SIZE), -1):
        if i < len(text) and text[i] in (" ", "\n", "\t"):
            return i + 1
    return end_pos


def split_text_into_chunks(text: str) -> list[str]:
    chunks = []
    pos = 0
    while pos < len(text):
        chunk_end = find_chunk_boundary(text, pos)
        chunk = text[pos:chunk_end].strip()
        if chunk:
            if len(chunk) > MAX_CHUNK_SIZE:
                chunk = chunk[:MAX_32768].rsplit(" ", 1)[0]
            chunks.append(chunk)
        pos = chunk_end
    return chunks


def process_file(path: Path, output_dir: Path) -> tuple[str, int, str | None]:
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
        if not text.strip():
            return (path.name, 0, None)
        chunks = split_text_into_chunks(text)
        if not chunks:
            return (path.name, 0, None)
        stem = path.stem
        suffix = path.suffix
        for i, chunk in enumerate(chunks, 1):
            chunk_filename = f"{stem}_{i}{suffix}"
            chunk_path = output_dir / chunk_filename
            with open(chunk_path, "w", encoding="utf-8") as f:
                f.write(chunk)
        return (path.name, len(chunks), None)
    except Exception as e:
        return (path.name, 0, str(e))


def get_text_files(paths: list[Path]) -> list[Path]:
    text_files = []
    text_extensions = {".txt", ".md", ".csv", ".log", ".json", ".yaml", ".yml", ".xml"}
    for path in paths:
        if path.is_file():
            if path.suffix.lower() in text_extensions or path.suffix == "":
                text_files.append(path)
        elif path.is_dir():
            for file in path.rglob("*"):
                if file.is_file() and file.suffix.lower() in text_extensions:
                    text_files.append(file)
    return text_files


def main():
    parser = argparse.ArgumentParser(
        description="Split text files into chunks (< 5000 chars) respecting word/sentence boundaries."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="output",
        help="Output directory for chunks (default: output)",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=cpu_count(),
        help=f"Number of parallel jobs (default: {cpu_count()})",
    )
    args = parser.parse_args()
    if args.inputs:
        input_paths = [Path(p) for p in args.inputs]
    else:
        input_paths = [Path.cwd()]
    output_dir = Path(args.output)
    output_dir.mkdir(exist_ok=True, parents=True)
    text_files = get_text_files(input_paths)
    if not text_files:
        print("No text files found.")
        return 1
    print(f"Found {len(text_files)} text file(s)")
    print(f"Processing with {args.jobs} parallel job(s)...")
    print("Target chunk size: < 5000 characters")
    with Pool(args.jobs) as pool:
        results = pool.starmap(process_file, [(f, output_dir) for f in text_files])
    total_chunks = 0
    errors = 0
    print("\nResults:")
    print("-" * 40)
    for filename, num_chunks, error in results:
        if error:
            print(f"❌ {filename}: {error}")
            errors += 1
        else:
            print(f"✓ {filename}: {num_chunks} chunk(s)")
            total_chunks += num_chunks
    print("-" * 40)
    print(f"Total chunks created: {total_chunks}")
    print(f"Output directory: {output_dir.resolve()}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
