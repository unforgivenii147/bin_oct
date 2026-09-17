#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

import ffmpeg


def get_subtitle_streams_info(input_path: str) -> list[dict]:
    try:
        probe_data = ffmpeg.probe(input_path, select_streams="s")
        streams_info = []
        for stream in probe_data.get("streams", []):
            print(stream)
            if stream.get("codec_type") == "subtitle":
                stream_info = {
                    "index": stream.get("index"),
                    "language": stream.get("tags", {}).get("language", "und"),
                    "title": stream.get("tags", {}).get("title"),
                    "forced": stream.get("disposition", {}).get("forced", 0) == 1,
                    "codec_name": stream.get("codec_name"),
                }
                print(stream_info)
                streams_info.append(stream_info)
        return streams_info
    except ffmpeg.Error as e:
        print(f"Error probing file: {e.stderr.decode('utf8')}")
        return []


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <video.mkv|video.mp4>")
        sys.exit(1)
    input_path_str = sys.argv[1]
    input_path = Path(input_path_str)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        sys.exit(1)
    basename = input_path.with_suffix("")
    subtitle_streams = get_subtitle_streams_info(input_path_str)
    print(subtitle_streams)
    if not subtitle_streams:
        print("No subtitle streams found.")
        sys.exit(0)
    print(f"Found {len(subtitle_streams)} subtitle streams.")
    try:
        extracted_files = []
        for _i, stream_info in enumerate(subtitle_streams):
            index = stream_info["index"]
            lang = stream_info["language"]
            title = stream_info["title"]
            forced = stream_info["forced"]
            codec_name = stream_info["codec_name"]
            filename_parts = [str(basename)]
            filename_parts.append(f"sub{index}")
            if lang != "und":
                filename_parts.append(lang)
            if title:
                safe_title = "".join(c if c.isalnum() else "_" for c in title)
                filename_parts.append(safe_title)
            if forced:
                filename_parts.append("forced")
            out_filename = ".".join(filename_parts) + ".srt"
            out_path = Path(out_filename)
            extracted_files.append(str(out_path))
    except:
        print(
            f"Extracting stream index {index} (Lang: {lang}, Forced: {forced}, Codec: {codec_name}) -> {out_path}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
