#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import logging
import sys
from pathlib import Path

import babelfish
from subliminal import download_best_subtitles, save_subtitles
from subliminal.video import scan_video

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def download_subtitles_advanced(mkv_path, output_dir=None):
    mkv_path = Path(mkv_path)
    if not mkv_path.exists():
        logger.error(f"File not found: {mkv_path}")
        return False
    if output_dir is None:
        output_dir = mkv_path.parent
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    try:
        video = scan_video(mkv_path)
        print(f"Processing: {video.name}")
    except Exception as e:
        logger.error(f"Error scanning: {e}")
        return False
    providers = ["opensubtitles", "podnapisi", "addic7ed", "tvsubtitles"]
    language = babelfish.Language("eng")
    try:
        subtitles = download_best_subtitles([video], {language}, providers=providers)
        video_subtitles = subtitles.get(video, {})
        if not video_subtitles:
            logger.warning("No English subtitles found")
            return False
        subtitle_path = output_dir / f"{mkv_path.stem}.en.srt"
        save_subtitles(video, video_subtitles, single=True, path=subtitle_path)
        print(f"✓ Subtitles saved: {subtitle_path}")
        return True
    except Exception as e:
        logger.error(f"Error: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python subtitle_downloader.py <movie.mkv> [output_dir]")
        sys.exit(1)
    success = download_subtitles_advanced(
        sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None
    )
    sys.exit(0 if success else 1)
