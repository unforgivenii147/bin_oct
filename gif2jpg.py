#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
from joblib import Parallel, delayed
from PIL import Image, UnidentifiedImageError

SEARCH_ROOT = Path(".")
JPEG_QUALITY = 90
SIMILARITY_THRESHOLD = 8.0
MIN_CHANGED_PIXEL_FRACTION = 0.005
N_JOBS = -1
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


def frames_are_similar(arr_a: np.ndarray, arr_b: np.ndarray) -> bool:
    if arr_a.shape != arr_b.shape:
        return False
    diff = np.abs(arr_a.astype(np.int16) - arr_b.astype(np.int16))
    mean_diff = diff.mean()
    changed_fraction = (diff > 10).any(axis=-1).mean()
    return (
        mean_diff < SIMILARITY_THRESHOLD
        and changed_fraction < MIN_CHANGED_PIXEL_FRACTION
    )


def extract_unique_frames(gif_path: Path) -> list[np.ndarray]:
    frames: list[np.ndarray] = []
    try:
        with Image.open(gif_path) as img:
            if not hasattr(img, "n_frames"):
                canvas = Image.new("RGB", img.size, (255, 255, 255))
                canvas.paste(
                    img.convert("RGBA"),
                    mask=img.convert("RGBA").split()[3]
                    if img.mode in ("RGBA", "P")
                    else None,
                )
                frames.append(np.asarray(canvas))
                return frames
            canvas = Image.new("RGB", img.size, (255, 255, 255))
            prev_frame_img: Image.Image | None = None
            for frame_idx in range(img.n_frames):
                img.seek(frame_idx)
                disposal = img.info.get("disposal", 0)
                if disposal == 3 and prev_frame_img is not None:
                    canvas = prev_frame_img.copy()
                elif disposal == 2:
                    canvas = Image.new("RGB", img.size, (255, 255, 255))
                prev_frame_img = canvas.copy()
                frame = img.convert("RGBA")
                canvas.paste(frame, mask=frame.split()[3])
                arr = np.asarray(canvas.convert("RGB"))
                if frames and frames_are_similar(frames[-1], arr):
                    log.debug(
                        "  Skipping near-duplicate frame %d in %s",
                        frame_idx,
                        gif_path.name,
                    )
                    continue
                frames.append(arr)
    except (UnidentifiedImageError, OSError) as exc:
        log.error("Cannot open %s: %s", gif_path, exc)
    return frames


def convert_gif(gif_path: Path) -> tuple[Path, int, int]:
    frames = extract_unique_frames(gif_path)
    if not frames:
        log.warning("No usable frames in %s", gif_path)
        return gif_path, 0, 0
    total_in_gif = 0
    try:
        with Image.open(gif_path) as probe:
            total_in_gif = getattr(probe, "n_frames", 1)
    except OSError:
        pass
    stem = gif_path.stem
    out_dir = gif_path.parent
    zero_pad = len(str(len(frames)))
    saved = 0
    for idx, arr in enumerate(frames):
        if len(frames) == 1:
            out_path = out_dir / f"{stem}.jpg"
        else:
            out_path = out_dir / f"{stem}_frame{idx:0{zero_pad}d}.jpg"
        if out_path.exists() and out_path.stat().st_mtime >= gif_path.stat().st_mtime:
            log.debug("  Up-to-date, skipping: %s", out_path.name)
            saved += 1
            continue
        img = Image.fromarray(arr, mode="RGB")
        try:
            img.save(out_path, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            saved += 1
        except OSError as exc:
            log.error("Failed to save %s: %s", out_path, exc)
    log.info(
        "%-50s  %d/%d frames kept → %d JPG(s)",
        str(gif_path),
        len(frames),
        total_in_gif,
        saved,
    )
    return gif_path, total_in_gif, saved


def main() -> None:
    gif_files = sorted(SEARCH_ROOT.rglob("*.gif"))
    gif_files += sorted(SEARCH_ROOT.rglob("*.GIF"))
    seen: set[Path] = set()
    unique_gifs: list[Path] = []
    for p in gif_files:
        r = p.resolve()
        if r not in seen:
            seen.add(r)
            unique_gifs.append(p)
    if not unique_gifs:
        log.info("No GIF files found under %s", SEARCH_ROOT.resolve())
        return
    log.info(
        "Found %d GIF file(s). Starting conversion with %s workers…",
        len(unique_gifs),
        "all CPUs" if N_JOBS == -1 else str(N_JOBS),
    )
    results = Parallel(n_jobs=N_JOBS, backend="loky", verbose=0)(
        delayed(convert_gif)(p) for p in unique_gifs
    )
    total_gifs = len(results)
    total_frames = sum(r[1] for r in results)
    total_saved = sum(r[2] for r in results)
    log.info(
        "Done. %d GIF(s) processed — %d/%d frames saved as JPG.",
        total_gifs,
        total_saved,
        total_frames,
    )


if __name__ == "__main__":
    raise SystemExit(main())
