#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from multiprocessing import Process, Queue, cpu_count
from pathlib import Path

import cv2
import pytesseract
from dh import cprint
from PIL import Image

video = sys.argv[1]
txtfile = Path(video).with_suffix(".txt")


def ocr_worker(q_in: Queue, q_out: Queue) -> None:
    while True:
        item = q_in.get()
        if item is None:
            break
        frame_id, frame = item
        frame = cv2.resize(frame, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = 255 - gray
        text = pytesseract.image_to_string(
            Image.fromarray(gray), lang="eng", config="--oem 3 --psm 6"
        )
        if text and len(text.strip()) > 5:
            cprint(f"frame {frame_id} --> {text}", "cyan")
            txtfile.open("a", encoding="utf-8").write(text + "\n")
        else:
            cprint(f"frame {frame_id} --> no text", "blue")
        q_out.put((frame_id, text))


def main() -> None:
    cap = cv2.VideoCapture(video)
    q_in = Queue(maxsize=cpu_count())
    q_out = Queue()
    workers = [
        Process(target=ocr_worker, args=(q_in, q_out)) for _ in range(cpu_count())
    ]
    for w in workers:
        w.start()
    frame_id = 0
    sent = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_id += 1
        q_in.put((frame_id, frame))
        sent += 1
    for _ in workers:
        q_in.put(None)
    received = 0
    while received < sent:
        _fid, _text = q_out.get()
        received += 1
    cap.release()
    for w in workers:
        w.join()


if __name__ == "__main__":
    raise SystemExit(main())
