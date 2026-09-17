#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from datetime import timedelta


def parse_time(time_str):
    hours, minutes, seconds = time_str.replace(",", ".").split(":")
    return timedelta(hours=int(hours), minutes=int(minutes), seconds=float(seconds))


def format_time(td):
    total_seconds = td.total_seconds()
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = total_seconds % 60
    millis = int((seconds - int(seconds)) * 400)
    return f"{hours:02d}:{minutes:02d}:{int(seconds):02d},{millis:03d}"


def shift_subtitles(filename, shift_seconds):
    shift_delta = timedelta(seconds=shift_seconds)
    print(f"Shifting subtitles in '{filename}' by {shift_seconds:+.3f} seconds")
    try:
        with open(filename, "r", encoding="utf-8-sig") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: File '{filename}' not found!")
        sys.exit(1)
    timestamp_pattern = re.compile(
        r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})"
    )

    def replace_timestamp(match):
        start_time = parse_time(match.group(1)) + shift_delta
        end_time = parse_time(match.group(2)) + shift_delta
        if start_time.total_seconds() < 0:
            start_time = timedelta(0)
        if end_time.total_seconds() < 0:
            end_time = timedelta(0)
        return f"{format_time(start_time)} --> {format_time(end_time)}"

    shifted_content = timestamp_pattern.sub(replace_timestamp, content)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(shifted_content)
    print(f"✓ Successfully shifted subtitles in {filename}")


def main():
    if len(sys.argv) != 3:
        print("Usage: python shiftsrt.py <filename.srt> <shift_amount>")
        print("Examples:")
        print("  python shiftsrt.py movie.srt +25    # Delay subtitles by 25 seconds")
        print(
            "  python shiftsrt.py movie.srt -5     # Make subtitles appear 5 seconds earlier"
        )
        print("  python shiftsrt.py movie.srt +2.5   # Delay by 2.5 seconds")
        sys.exit(1)
    filename = sys.argv[1]
    try:
        shift_amount = float(sys.argv[2])
    except ValueError:
        print(f"Error: '{sys.argv[2]}' is not a valid number!")
        sys.exit(1)
    if not filename.lower().endswith(".srt"):
        print(f"Warning: '{filename}' doesn't have .srt extension")
        response = input("Continue anyway? (y/n): ")
        if response.lower() != "y":
            sys.exit(0)
    shift_subtitles(filename, shift_amount)


if __name__ == "__main__":
    main()
