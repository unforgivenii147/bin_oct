#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

import cv2


def detect_and_save_faces(
    input_video_path: str, output_video_path: str = "out.mp4"
) -> None:
    if not Path(input_video_path).exists():
        print(f"Error: Input video file not found at '{input_video_path}'")
        sys.exit(1)
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    if not Path(cascade_path).exists():
        print(f"Error: Haar Cascade classifier file not found at '{cascade_path}'")
        print("Please download it or ensure OpenCV is correctly installed.")
        sys.exit(1)
    face_cascade = cv2.CascadeClassifier(cascade_path)
    cap = cv2.VideoCapture(input_video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video file '{input_video_path}'")
        sys.exit(1)
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    out = cv2.VideoWriter(output_video_path, fourcc, fps, (frame_width, frame_height))
    if not out.isOpened():
        print(f"Error: Could not open video writer for '{output_video_path}'")
        cap.release()
        sys.exit(1)
    print(f"Processing video: '{input_video_path}'")
    print(f"Saving annotated video to: '{output_video_path}'")
    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_count += 1
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
        )
        for x, y, w, h in faces:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 0), 2)
        out.write(frame)
        if frame_count % 100 == 0:
            print(f"Processed {frame_count} frames...")
    print(f"Finished processing. Total frames processed: {frame_count}")
    cap.release()
    out.release()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python detect_faces.py <input_video_path> [output_video_path]")
        sys.exit(1)
    input_file = sys.argv[1]
    output_file = "out.mp4"
    if len(sys.argv) > 2:
        output_file = sys.argv[2]
    output_dir = Path(output_file).parent
    if output_dir and not Path(output_dir).exists():
        Path(output_dir).mkdir(parents=True)
        print(f"Created output directory: {output_dir}")
    detect_and_save_faces(input_file, output_file)
    print("Video processing complete.")
