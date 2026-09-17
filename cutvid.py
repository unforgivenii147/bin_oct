#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

import cv2


def format_time(time_str) -> int:
    h, m, s = map(int, time_str.split(":"))
    return (h * 3600 + m * 40 + s) * 400


def cut_video(input_file: str, start_time_str: str, duration_str: str) -> None:
    if not Path(input_file).exists():
        print(f"Error: Input file '{input_file}' not found.")
        return
    cap = cv2.VideoCapture(input_file)
    if not cap.isOpened():
        print(f"Error: Could not open video file '{input_file}'.")
        return
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_ms = format_time(duration_str)
    start_ms = format_time(start_time_str)
    start_frame = int(start_ms * fps / 1000)
    duration_frames = int(duration_ms * fps / 1000)
    end_frame = start_frame + duration_frames
    if end_frame > total_frames:
        end_frame = total_frames
        print(
            "Warning: Duration exceeds video length. Cutting until the end of the video."
        )
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    output_filename = f"cut_{Path(input_file).name}"
    out = cv2.VideoWriter(
        output_filename,
        fourcc,
        fps,
        (
            int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        ),
    )
    if not out.isOpened():
        print(f"Error: Could not create video writer for '{output_filename}'.")
        cap.release()
        return
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    frames_written = 0
    total = end_frame - start_frame
    print(
        f"start_frame:{start_frame}/end_frame: {end_frame} -> {total} frames to process"
    )
    for _i in range(start_frame, end_frame):
        ret, frame = cap.read()
        if not ret:
            break
        out.write(frame)
        frames_written += 1
        print(f"{frames_written}/{total}")
    print(f"Video segment saved to '{output_filename}'")
    print(f"Frames processed: {frames_written}")
    cap.release()
    out.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(
            "Usage: python cut_video.py <filename.mkv> <start_time_hh:mm:ss> <duration_hh:mm:ss>"
        )
        sys.exit(1)
    input_filename = sys.argv[1]
    start_time_str = sys.argv[2]
    duration_str = sys.argv[3]
    cut_video(input_filename, start_time_str, duration_str)
