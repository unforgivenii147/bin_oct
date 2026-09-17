#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import sys
from pathlib import Path

import ffmpy


def get_subtitle_streams(input_file):
    ff = ffmpy.FFprobe(
        inputs={input_file: None},
        global_options=[
            "-v",
            "error",
            "-select_streams",
            "s",
            "-show_entries",
            "stream=index:stream_tags=language",
            "-of",
            "json",
        ],
    )
    try:
        stdout, _stderr = ff.run(stdout=True, stderr=True)
        data = json.loads(stdout.decode())
        return data.get("streams", [])
    except ffmpy.FFExecutableNotFoundError:
        print("ffmpeg/ffprobe is required but not installed.")
        sys.exit(1)
    except Exception as e:
        print(f"Error probing file: {e}")
        sys.exit(1)


def extract_subtitle(input_file, stream_index, output_file):
    ff = ffmpy.FFmpeg(
        inputs={input_file: None},
        outputs={output_file: f"-map 0:s:{stream_index}"},
        global_options=["-y"],
    )
    try:
        ff.run(stdout=False, stderr=False)
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <video.mkv|video.mp4>")
        sys.exit(1)
    input_file = sys.argv[1]
    if not Path(input_file).exists():
        print(f"File not found: {input_file}")
        sys.exit(1)
    streams = get_subtitle_streams(input_file)
    if not streams:
        print("No subtitle streams found.")
        sys.exit(0)
    basename = Path(input_file).stem
    for i, stream in enumerate(streams):
        lang = stream.get("tags", {}).get("language", "und")
        output_file = f"{basename}.sub{i}.{lang}.srt"
        print(f"Extracting subtitle stream {stream['index']} -> {output_file}")
        extract_subtitle(input_file, i, output_file)
    print("Done.")


if __name__ == "__main__":
    raise SystemExit(main())
