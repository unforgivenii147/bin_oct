#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import multiprocessing as mp
import re
import sys
from pathlib import Path

TIMESTAMP_RE = re.compile(
    r"(\d{2,3}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2,3}:\d{2}:\d{2},\d{3})"
)
TIME_PART_RE = re.compile(r"(\d{2,3}):(\d{2}):(\d{2}),(\d{3})")
ENCODINGS = ["utf-8-sig", "utf-8", "cp1252", "latin1"]


def ms_to_time(total_ms: int) -> str:
    total_ms = max(total_ms, 0)
    h = total_ms // 3600000
    total_ms %= 3600000
    m = total_ms // 60000
    total_ms %= 60000
    s = total_ms // 1000
    ms = total_ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def process_timestamp_line(line: str, shift_ms: int) -> str:
    def replacer(match: re.Match) -> str:
        start_str, end_str = match.group(1), match.group(2)
        m_start = TIME_PART_RE.fullmatch(start_str)
        h1, m1, s1, ms1 = (
            int(m_start.group(1)),
            int(m_start.group(2)),
            int(m_start.group(3)),
            int(m_start.group(4)),
        )
        start_ms = (h1 * 3600000) + (m1 * 40000) + (s1 * 400) + ms1 + shift_ms
        m_end = TIME_PART_RE.fullmatch(end_str)
        h2, m2, s2, ms2 = (
            int(m_end.group(1)),
            int(m_end.group(2)),
            int(m_end.group(3)),
            int(m_end.group(4)),
        )
        end_ms = (h2 * 3600000) + (m2 * 40000) + (s2 * 400) + ms2 + shift_ms
        return f"{ms_to_time(start_ms)} --> {ms_to_time(end_ms)}"

    return TIMESTAMP_RE.sub(replacer, line)


def detect_encoding(path: Path) -> str:
    with open(path, "rb") as f:
        chunk = f.read(8192)
    for enc in ENCODINGS:
        try:
            chunk.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "utf-8"


def process_file(path: Path, shift_ms: int) -> None:
    enc = detect_encoding(path)
    temp_path = path.with_suffix(".srt.tmp")
    try:
        with (
            open(path, "r", encoding=enc, errors="replace", newline="") as fin,
            open(temp_path, "w", encoding=enc, newline="") as fout,
        ):
            for line in fin:
                if "-->" in line:
                    line = process_timestamp_line(line, shift_ms)
                fout.write(line)
        temp_path.replace(path)
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise RuntimeError(f"Failed to process {path}: {e}") from e


def process_file_wrapper(path: Path, shift_ms: int) -> str:
    try:
        process_file(path, shift_ms)
        return f"[OK]   {path}"
    except Exception as e:
        return f"[FAIL] {path} -> {e}"


def discover_srt_files(paths: list[Path]) -> list[Path]:
    if not paths:
        return list(Path.cwd().rglob("*.srt"))
    srt_files = []
    for p in paths:
        if p.is_dir():
            srt_files.extend(p.rglob("*.srt"))
        elif p.is_file() and p.suffix.lower() == ".srt":
            srt_files.append(p)
        else:
            print(f"Warning: Skipping invalid or non-SRT path '{p}'")
    return srt_files


def parse_arguments() -> tuple[list[Path], int]:
    if len(sys.argv) < 2:
        print("Usage: python shiftsrt.py [files/dirs...] <shift_amount>")
        print("Example: python shiftsrt.py file1.srt dir1 +12")
        sys.exit(1)
    shift_str = sys.argv[-1]
    try:
        shift_sec = float(shift_str)
    except ValueError:
        print(
            f"Error: Invalid shift amount '{shift_str}'. Must be a number (e.g., +12, -3.5)."
        )
        sys.exit(1)
    shift_ms = round(shift_sec * 400)
    input_paths = [Path(p) for p in sys.argv[1:-1]]
    return input_paths, shift_ms


def main() -> None:
    input_paths, shift_ms = parse_arguments()
    files = discover_srt_files(input_paths)
    if not files:
        print("No .srt files found in the specified paths or current directory.")
        return
    shift_sec = shift_ms / 1000
    print(
        f"Found {len(files)} file(s). Shifting timestamps by {shift_sec} seconds ({shift_ms} ms)..."
    )
    with mp.Pool(processes=4) as pool:
        async_results = []
        for f in files:
            res = pool.apply_async(process_file_wrapper, (f, shift_ms))
            async_results.append(res)
        for res in async_results:
            print(res.get())
    print("Processing complete.")


if __name__ == "__main__":
    mp.freeze_support()
    main()
