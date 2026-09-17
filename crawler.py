#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import os
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dh import cprint

BASE_URL = "https://dls2.aparatchi-dlcenter.top/DonyayeSerial/"
OUTPUT_FILE = "movies.txt"
STATE_FILE = "crawler_state.json"
MAX_SIZE_MB = 300
visited: set[str] = set()
found_movies: list[str] = []


def size_to_mb(size_str: str) -> float | None:
    if not size_str or size_str.strip() == "-":
        return None
    match = re.search(r"([\d.]+)\s*([KMG]?)i?B?", size_str.strip())
    if match:
        value = float(match.group(1))
        unit = match.group(2).upper()
        if unit == "G":
            return value * 1024
        elif unit == "M":
            return value
        elif unit == "K":
            return value / 1024
        else:
            return value / 1024 / 1024
    return None


def is_valid_movie(filename: str, size_mb: float | None) -> bool:
    if not filename:
        return False
    if not (filename.lower().endswith(".mkv") or filename.lower().endswith(".mp4")):
        return False
    if not ("480p" in filename.lower() or "720p" in filename.lower()):
        return False
    if size_mb is None or size_mb >= MAX_SIZE_MB:
        return False
    cprint(f"{filename} {size_mb:.2f} MB")
    return True


def save_state():
    state = {"visited": list(visited), "found_movies": found_movies}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def load_state():
    global visited, found_movies
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
                visited = set(state.get("visited", []))
                found_movies = state.get("found_movies", [])
                print(
                    f"📂 Loaded previous state: {len(visited)} visited, {len(found_movies)} movies found"
                )
                return True
        except Exception as e:
            print(f"⚠️ Error loading state: {e}")
    return False


def save_movie(url: str):
    if url not in found_movies:
        found_movies.append(url)
        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
            f.write(url + "\n")


def crawl(url: str, depth: int = 0) -> None:
    if url in visited:
        return
    if "movie" in url.lower():
        return
    print(f"{'  ' * depth}Crawling: {url}")
    visited.add(url)
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ Failed to access {url}: {e}")
        return
    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.find_all("tr")
    if not rows:
        rows = soup.select("table tbody tr")
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 3:
            continue
        link_cell = cols[0]
        link_tag = link_cell.find("a")
        if not link_tag:
            continue
        name = link_tag.text.strip()
        href = link_tag.get("href")
        if not href:
            continue
        size_text = cols[2].text.strip() if len(cols) > 2 else ""
        size_mb = size_to_mb(size_text)
        full_url = urljoin(url, href)
        if "Parent directory" in name or "Parent Directory" in name:
            continue
        if href.endswith("/"):
            crawl(full_url, depth + 1)
        else:
            if is_valid_movie(name, size_mb):
                print(f"✅ Found: {full_url} ({size_mb:.2f} MB)")
                save_movie(full_url)
                save_state()


def main():
    global found_movies
    print("🎬 Movie Crawler with Resume Support")
    print("=" * 40)
    loaded = load_state()
    if not loaded and os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing_movies = [line.strip() for line in f if line.strip()]
                found_movies = existing_movies
                print(f"📂 Loaded {len(found_movies)} movies from {OUTPUT_FILE}")
        except Exception as e:
            print(f"⚠️ Could not load existing movie file: {e}")
    print("\n🔍 Starting crawl...")
    try:
        crawl(BASE_URL)
    except KeyboardInterrupt:
        print("\n⏹️ Interrupted by user. Saving state...")
        save_state()
        print("💾 State saved. Run again to resume.")
        return
    save_state()
    print(f"\n✅ Done. {len(found_movies)} movies saved to {OUTPUT_FILE}")
    if found_movies:
        print("\n📋 First 5 movies found:")
        for url in found_movies[:5]:
            print(f"  • {url}")
        if len(found_movies) > 5:
            print(f"  ... and {len(found_movies) - 5} more")


if __name__ == "__main__":
    raise SystemExit(main())
