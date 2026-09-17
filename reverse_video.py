#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
import sys


def reverse_video_ffmpeg(input_file, output_file="reversed.mp4"):
    cmd = [
        "ffmpeg",
        "-i",
        input_file,
        "-vf",
        "reverse",
        "-af",
        "areverse",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        output_file,
    ]
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print(f"Saved to {output_file}")


def reverse_video_ffmpeg_fast(input_file, output_file="reversed.mp4"):
    cmd = [
        "ffmpeg",
        "-i",
        input_file,
        "-vf",
        "reverse",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "23",
        output_file,
    ]
    subprocess.run(cmd, check=True)
    print(f"Saved to {output_file}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <input_video_file>")
        sys.exit(1)
    reverse_video_ffmpeg_fast(sys.argv[1])
