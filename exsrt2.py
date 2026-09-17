#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess


def extract_subtitles(video_path) -> None:
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True)
    except FileNotFoundError:
        raise FileNotFoundError("ffmpeg is required but not installed.")
    basename = video_path.rsplit(".", 1)[0]
    ffprobe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "s",
        "-show_entries",
        "stream=index:stream_tags=language",
        "-of",
        "csv=p=0",
        video_path,
    ]
    subs_output = subprocess.run(
        ffprobe_cmd, capture_output=True, text=True, check=True
    )
    subs = subs_output.stdout.strip().split("\n")
    if not subs or (len(subs) == 1 and subs[0] == ""):
        print("No subtitle streams found.")
        return
    count = 0
    for line in subs:
        index, lang = line.split(",")
        if not lang:
            lang = "und"
        out_filename = f"{basename}.sub{count}.{lang}.srt"
        print(f"Extracting subtitle stream {index} -> {out_filename}")
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-map",
            f"0:s:{count}",
            out_filename,
        ]
        subprocess.run(ffmpeg_cmd, check=True, capture_output=True)
        count += 1
    print("Done.")


if __name__ == "__main__":
    import sys

    fn = sys.argv[1].strip()
    extract_subtitles(fn)
