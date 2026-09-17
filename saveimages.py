#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


def download_image(url, output_dir) -> None:
    try:
        response = requests.get(url, stream=True, timeout=5)
        response.raise_for_status()
        filename = os.path.join(output_dir, Path(url).name)
        with Path(filename).open("wb") as f:
            f.writelines(response.iter_content(1024))
        print(f"Downloaded: {filename}")
    except Exception as e:
        print(f"Failed to download {url}: {e}")


def extract_images_from_url(url, output_dir) -> None:
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        img_tags = soup.find_all("img")
        if not Path(output_dir).exists():
            Path(output_dir).mkdir(parents=True)
        for img in img_tags:
            img_url = img.get("src")
            if img_url:
                img_url = urljoin(url, img_url)
                download_image(img_url, output_dir)
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract images from a URL and save them to an output directory."
    )
    parser.add_argument("url", type=str, help="URL to extract images from")
    parser.add_argument(
        "output_dir", default="output", type=str, help="Output directory to save images"
    )
    args = parser.parse_args()
    extract_images_from_url(args.url, args.output_dir)
