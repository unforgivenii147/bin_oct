#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <filename>")
        sys.exit(1)
    fname = sys.argv[1]
    llen = int(str(sys.argv[2]).strip()) if len(sys.argv) == 3 else 10
    lines = []
    try:
        with Path(fname).open(encoding="utf-8") as f:
            lines = f.readlines()
        filtered = [line for line in lines if len(line.strip()) >= llen]
        with Path(fname).open("w", encoding="utf-8") as f:
            f.writelines(filtered)
    except FileNotFoundError:
        print(f"Error: File '{fname}' not found.")
    except Exception as e:
        print("An error occurred:", e)
