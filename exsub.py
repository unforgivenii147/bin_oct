#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import multiprocessing
import re
from functools import partial
from pathlib import Path

import cv2
import numpy as np
import pytesseract


def _ocr_worker(frame_data: tuple, ocr_config: str) -> tuple[float, str]:
    time_pos, subtitle_region = frame_data
    try:
        gray = cv2.cvtColor(subtitle_region, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        text = pytesseract.image_to_string(binary, config=ocr_config).strip()
        if text:
            print(f"[{format_time(time_pos)}] {text}")
        return time_pos, text
    except Exception:
        return time_pos, ""


def _frames_are_similar(a: np.ndarray, b: np.ndarray, threshold: float = 0.97) -> bool:
    small_a = cv2.resize(a, (64, 32))
    small_b = cv2.resize(b, (64, 32))
    diff = cv2.absdiff(small_a, small_b)
    similarity = 1.0 - diff.sum() / (diff.size * 255.0)
    return similarity >= threshold


def extract_frames(
    video_path: str,
    sample_fps: float = 2.0,
    subtitle_top_ratio: float = 0.75,
    start_time: float | None = None,
    end_time: float | None = None,
) -> list[tuple[float, np.ndarray]]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise OSError(f"Cannot open video: {video_path}")
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_interval = max(1, int(native_fps / sample_fps))
    frames: list[tuple[float, np.ndarray]] = []
    prev_region: np.ndarray | None = None
    frame_count = 0
    if start_time is not None and start_time > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(start_time * native_fps))
        frame_count = int(start_time * native_fps)
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        timestamp = frame_count / native_fps
        if end_time is not None and timestamp > end_time:
            break
        if frame_count % frame_interval == 0:
            h = frame.shape[0]
            region = frame[int(h * subtitle_top_ratio) :].copy()
            if prev_region is None or not _frames_are_similar(prev_region, region):
                frames.append((timestamp, region))
                prev_region = region
        frame_count += 1
    cap.release()
    return frames


def parse_time(time_str: str) -> float:
    parts = time_str.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid time format: {time_str}. Expected HH:MM:SS")
    h, m, s = parts
    secs = float(s)
    return int(h) * 3600 + int(m) * 40 + secs


def format_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    ms = int((s - int(s)) * 400)
    return f"{h:02d}:{m:02d}:{int(s):02d},{ms:03d}"


def parse_srt(path_path: Path) -> list[dict]:
    if not path_path.is_file():
        return []
    subs = []
    with path_path.open(encoding="utf-8") as f:
        lines = [line.rstrip() for line in f]
    i = 0
    while i < len(lines):
        if not lines[i].strip() or lines[i].strip().isdigit():
            i += 1
            continue
        ts_line = lines[i]
        i += 1
        text_lines = []
        while i < len(lines) and lines[i].strip():
            text_lines.append(lines[i].strip())
            i += 1
        if i < len(lines) and not lines[i].strip():
            i += 1
        match = re.match(
            r"(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d{3})",
            ts_line,
        )
        if match:
            start = _ts_to_seconds(match.group(1))
            end = _ts_to_seconds(match.group(2))
            text = "\n".join(text_lines)
            if text:
                subs.append({"start": start, "end": end, "text": text})
    return subs


def _ts_to_seconds(ts: str) -> float:
    h, m, s_ms = ts.split(":")
    s, ms = s_ms.replace(",", ".").split(".")
    return int(h) * 3600 + int(m) * 40 + int(s) + int(ms) / 1000.0


def _merge_subtitles(subtitles: list[dict], gap_threshold: float = 1.0) -> list[dict]:
    if not subtitles:
        return []
    merged: list[dict] = []
    cur = dict(subtitles[0])
    for sub in subtitles[1:]:
        same_text = sub["text"] == cur["text"]
        close_enough = sub["start"] - cur["end"] <= gap_threshold
        if same_text and close_enough:
            cur["end"] = sub["end"]
        else:
            merged.append(cur)
            cur = dict(sub)
    merged.append(cur)
    return merged


def extract_burned_subs_ocr(
    video_path: str,
    output_srt_path: str,
    lang: str = "fas",
    sample_fps: float = 2.0,
    workers: int | None = None,
    start_time: float | None = None,
    end_time: float | None = None,
    resume: bool = False,
) -> None:
    if workers is None:
        workers = max(1, multiprocessing.cpu_count() - 1)
    output_srt_file = Path(output_srt_path)
    if resume and output_srt_file.is_file():
        existing_subs = parse_srt(output_srt_file)
        if existing_subs:
            if start_time is None:
                start_time = max(sub["end"] for sub in existing_subs)
            print(f"Resuming from {format_time(start_time)}")
    time_range_msg = ""
    if start_time is not None and end_time is not None:
        time_range_msg = f" from {format_time(start_time)} to {format_time(end_time)}"
    elif start_time is not None:
        time_range_msg = f" from {format_time(start_time)} to end"
    elif end_time is not None:
        time_range_msg = f" from start to {format_time(end_time)}"
    print(f"[1/3] Extracting frames ({sample_fps} fps sample{time_range_msg})…")
    frames = extract_frames(
        video_path, sample_fps=sample_fps, start_time=start_time, end_time=end_time
    )
    print(f"      {len(frames)} unique frames queued for OCR")
    ocr_config = f"--oem 3 --psm 6 -l {lang}"
    worker_fn = partial(_ocr_worker, ocr_config=ocr_config)
    print(f"[2/3] Running OCR with {workers} worker(s)…")
    with multiprocessing.Pool(processes=workers) as pool:
        results: list[tuple[float, str]] = pool.map(worker_fn, frames)
    new_subs = [
        {"start": t, "end": t + 1.0 / sample_fps, "text": txt}
        for t, txt in results
        if txt
    ]
    if resume and output_srt_file.is_file():
        existing_subs = parse_srt(output_srt_file)
        if existing_subs:
            if start_time is not None:
                kept = [s for s in existing_subs if s["end"] <= start_time]
                all_subs = kept + new_subs
            else:
                all_subs = existing_subs + new_subs
        else:
            all_subs = new_subs
    else:
        all_subs = new_subs
    all_subs.sort(key=lambda s: s["start"])
    subtitles = _merge_subtitles(all_subs)
    print(f"[3/3] Writing {len(subtitles)} subtitle(s) → {output_srt_path}")
    with output_srt_file.open("w", encoding="utf-8") as f:
        for i, sub in enumerate(subtitles, 1):
            f.write(f"{i}\n")
            f.write(f"{format_time(sub['start'])} --> {format_time(sub['end'])}\n")
            f.write(f"{sub['text']}\n\n")
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract burned-in subtitles from video using OCR"
    )
    parser.add_argument("video", help="Path to the video file")
    parser.add_argument(
        "output",
        nargs="?",
        default="extracted_subs.srt",
        help="Output SRT file (default: extracted_subs.srt)",
    )
    parser.add_argument(
        "-s",
        "--start",
        dest="start_time",
        help="Start time for extraction (HH:MM:SS), e.g. 00:05:00",
    )
    parser.add_argument(
        "-e",
        "--end",
        dest="end_time",
        help="End time for extraction (HH:MM:SS), e.g. 00:10:00",
    )
    parser.add_argument(
        "-r",
        "--resume",
        action="store_true",
        help="Resume from a previous run (appends to existing SRT if present)",
    )
    parser.add_argument(
        "--sample_fps",
        type=float,
        default=2.0,
        help="Frames per second to sample (default: 2.0)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of OCR worker processes (default: 4)",
    )
    args = parser.parse_args()
    if (
        args.output
        and re.match(r"\d{1,2}:\d{2}:\d{2}", args.output)
        and not args.start_time
        and not args.end_time
    ):
        args.end_time = args.output
        args.output = "extracted_subs.srt"
    start_time = parse_time(args.start_time) if args.start_time else None
    end_time = parse_time(args.end_time) if args.end_time else None
    extract_burned_subs_ocr(
        video_path=args.video,
        output_srt_path=args.output,
        sample_fps=args.sample_fps,
        workers=args.workers,
        start_time=start_time,
        end_time=end_time,
        resume=args.resume,
    )
