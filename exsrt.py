#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
import sys


def main() -> None:
    input_file = sys.argv[1]
    output_file = input_file.replace(".mkv", ".srt")
    command = ["ffmpeg", "-i", input_file, "-map", "0:s:0", output_file]
    subprocess.run(command)


if __name__ == "__main__":
    raise SystemExit(main())
