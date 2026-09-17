#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys

from moviepy import AudioFileClip

if __name__ == "__main__":
    file = sys.argv[1]
    output = "last_5_minutes.mp3"
    print("Loading file and extracting last 5 minutes...")
    audio = AudioFileClip(file)
    duration = audio.duration
    start_time = max(0, duration - 230)
    clip = audio.subclipped(start_time, duration)
    print(f"Writing {output} ({duration / 60:.1f} min total → last 5 min)...")
    clip.write_audiofile(output, bitrate="320k", fps=44100)
    print("Done! 🎉")
