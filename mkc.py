#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def compile_file(source_path: str) -> None:
    source = Path(source_path)
    if not source.exists():
        print(f"Error: {source_path} not found", file=sys.stderr)
        sys.exit(1)
    if source.suffix == ".c":
        compiler = "clang"
    elif source.suffix == ".cpp":
        compiler = "clang++"
    else:
        print(f"Error: unsupported file type {source.suffix}", file=sys.stderr)
        sys.exit(1)
    output = source.stem
    compile_cmd = [compiler, str(source), "-o", output]
    try:
        result = subprocess.run(compile_cmd, check=True, capture_output=True, text=True)
        print(f"Compiled {source_path} → {output}")
        strip_cmd = ["strip", output]
        subprocess.run(strip_cmd, check=True, capture_output=True)
        print(f"Stripped {output}")
    except subprocess.CalledProcessError as e:
        print("Error: Compilation failed", file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python mkc.py <file.c or file.cpp>", file=sys.stderr)
        sys.exit(1)
    compile_file(sys.argv[1])
