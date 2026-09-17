#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

import ffmpeg


def extract_subtitles(input_file):
    try:
        probe = ffmpeg.probe(input_file)
        subtitle_streams = [
            stream for stream in probe["streams"] if stream["codec_type"] == "subtitle"
        ]
        if not subtitle_streams:
            print("No subtitle streams found.")
            return
        basename = Path(input_file).stem
        for i, stream in enumerate(subtitle_streams):
            lang = stream.get("tags", {}).get("language", "und")
            output_file = f"{basename}.sub{i}.{lang}.srt"
            print(f"Extracting subtitle stream {i} -> {output_file}")
            (
                ffmpeg.input(input_file)
                .output(output_file, map=f"0:s:{i}")
                .overwrite_output()
                .run(quiet=True)
            )
        print("Done.")
    except ffmpeg.Error as e:
        print(f"FFmpeg error: {e.stderr.decode() if e.stderr else e}")
        sys.exit(1)
    except FileNotFoundError:
        print("ffmpeg is required but not installed.")
        sys.exit(1)


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <video.mkv|video.mp4>")
        sys.exit(1)
    input_file = sys.argv[1]
    extract_subtitles(input_file)


if __name__ == "__main__":
    raise SystemExit(main())
