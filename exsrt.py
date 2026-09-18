#!/data/data/com.termux/files/home/.local/bin/python
import sys
from pathlib import Path

from py_subtitle_extractor import (
    extract_subtitle_tracks,
    extract_subtitles_as_srt,
)


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input.mkv> [track_number]")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = input_path.with_suffix(".srt")

    if not input_path.is_file():
        print(f"Error: file not found: {input_path}")
        sys.exit(1)

    # List available subtitle tracks
    tracks = extract_subtitle_tracks(str(input_path))
    if not tracks:
        print(f"No subtitle tracks found in {input_path}")
        sys.exit(1)

    print(f"Subtitle tracks in {input_path.name}:")
    for t in tracks:
        print(
            f"  Track #{t['track_number']}: {t['codec_id']} "
            f"[{t['language']}] – {t['name']}"
        )

    # Pick the requested track, or default to the first one
    if len(sys.argv) >= 3:
        try:
            track_number = int(sys.argv[2])
        except ValueError:
            print(f"Error: track number must be an integer, got {sys.argv[2]!r}")
            sys.exit(1)
    else:
        track_number = tracks[0]["track_number"]

    valid_numbers = {t["track_number"] for t in tracks}
    if track_number not in valid_numbers:
        print(
            f"Error: track #{track_number} not found. "
            f"Available: {sorted(valid_numbers)}"
        )
        sys.exit(1)

    print(f"\nExtracting track #{track_number} -> {output_path.name}")

    srt_text = extract_subtitles_as_srt(str(input_path), track_number)
    output_path.write_text(srt_text, encoding="utf-8")

    print("Done.")


if __name__ == "__main__":
    main()
