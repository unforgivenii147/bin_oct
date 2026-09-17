#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import logging
import sys
from pathlib import Path

import babelfish
from subliminal import download_best_subtitles, save_subtitles
from subliminal.providers import ProviderError
from subliminal.video import scan_video

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_english_subtitles(mkv_path, output_dir=None):
    mkv_path = Path(mkv_path)
    if not mkv_path.exists():
        logger.error(f"File not found: {mkv_path}")
        return False
    if mkv_path.suffix.lower() != ".mkv":
        logger.warning(f"File is not an MKV: {mkv_path}")
    if output_dir is None:
        output_dir = mkv_path.parent
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Scanning video: {mkv_path}")
    try:
        video = scan_video(mkv_path)
        print(f"Found video: {video.name}")
        print(f"  - Size: {video.size} bytes")
        print(f"  - Duration: {video.duration:.2f} seconds")
        print(f"  - Hashes: {video.hashes}")
    except Exception as e:
        logger.error(f"Error scanning video: {e}")
        return False
    language = babelfish.Language("eng")
    print("Searching for English subtitles...")
    try:
        subtitles = download_best_subtitles(
            [video],
            {language},
            providers=["opensubtitles", "podnapisi", "addic7ed", "tvsubtitles"],
        )
        video_subtitles = subtitles.get(video, {})
        if not video_subtitles:
            logger.warning(f"No English subtitles found for {mkv_path.name}")
            return False
        subtitle_path = output_dir / f"{mkv_path.stem}.srt"
        save_subtitles(video, video_subtitles, single=True, path=subtitle_path)
        print(f"Subtitles saved to: {subtitle_path}")
        return True
    except ProviderError as e:
        logger.error(f"Provider error: {e}")
        return False
    except Exception as e:
        logger.error(f"Error downloading subtitles: {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: python subtitle_downloader.py <path_to_mkv_file> [output_directory]"
        )
        print("Example: python subtitle_downloader.py movie.mkv")
        print(
            "Example: python subtitle_downloader.py /path/to/movie.mkv /path/to/subtitles/"
        )
        sys.exit(1)
    mkv_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    success = get_english_subtitles(mkv_path, output_dir)
    if success:
        print("✓ Subtitles downloaded successfully!")
    else:
        print("✗ Failed to download subtitles.")
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
