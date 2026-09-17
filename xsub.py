#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def run(cmd) -> str:
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def probe_subtitles(video_path):
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "s",
        "-show_entries",
        "stream=index,codec_name:stream_tags=language,title",
        "-of",
        "json",
        video_path,
    ]
    return json.loads(run(cmd)).get("streams", [])


def extract_subtitles(video_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    subs = probe_subtitles(video_path)
    if not subs:
        print("No embedded subtitle streams found.")
        return
    base = video_path.stem
    for s in subs:
        idx = s["index"]
        codec = s.get("codec_name", "sub")
        lang = s.get("tags", {}).get("language", "und")
        title = s.get("tags", {}).get("title", "").replace(" ", "_")
        suffix = f".{lang}"
        if title:
            out_ext = "srt" if codec in {"subrip", "srt"} else codec
        out_file = output_dir / f"{base}{suffix}.{out_ext}"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-map",
            f"0:s:{subs.index(s)}",
            str(out_file),
        ]
        try:
            run(cmd)
            print(f"Extracted: {out_file}")
        except RuntimeError as e:
            print(f"Failed to extract subtitle stream {idx}: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract embedded subtitles from a movie file"
    )
    parser.add_argument("movie", help="Path to movie file")
    parser.add_argument("-o", "--output", default="subtitles", help="Output directory")
    args = parser.parse_args()
    video_path = Path(args.movie).resolve()
    output_dir = Path(args.output).resolve()
    if not video_path.exists():
        raise FileNotFoundError(video_path)
    extract_subtitles(video_path, output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
