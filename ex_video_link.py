#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup


def extract_zzztube_link(zzztube_url: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        response = requests.get(zzztube_url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        return {"error": f"Failed to fetch URL: {e}"}
    soup = BeautifulSoup(response.content, "html.parser")
    config_json = None
    for script in soup.find_all("script", {"type": "application/json"}):
        try:
            data = json.loads(script.string)
            if "config" in data:
                config_json = data["config"]
                break
        except json.JSONDecodeError:
            continue
    video_id = None
    url_match = re.search(r"zzztube\.com/(\d+)", zzztube_url)
    if url_match:
        video_id = url_match.group(1)
    og_video = soup.find("meta", {"property": "og:video"})
    if og_video:
        video_src = og_video.get("content", "")
        if "zzztube" in video_src:
            id_match = re.search(r"/(\d+)", video_src)
            if id_match:
                video_id = id_match.group(1)
    title = None
    og_title = soup.find("meta", {"property": "og:title"})
    if og_title:
        title = og_title.get("content")
    iframe = soup.find("iframe", {"src": re.compile(r"zzztube")})
    iframe_src = iframe.get("src") if iframe else None
    playable_url = f"https://zzztube.com/{video_id}" if video_id else None
    return {
        "video_id": video_id,
        "title": title,
        "playable_url": playable_url,
        "iframe_src": iframe_src,
        "direct_url": f"https://player.zzztube.com/video/{video_id}"
        if video_id
        else None,
    }


def save_results_to_file(
    results: dict, output_file: str = "zzztube_links.json"
) -> Path:
    output_path = Path(output_file)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    return output_path


if __name__ == "__main__":
    urls = sys.argv[1:]
    all_results = []
    for url in urls:
        print(f"\n📹 Processing: {url}")
        result = extract_zzztube_link(url)
        all_results.append(result)
        if "error" in result:
            print(f"❌ {result['error']}")
        else:
            print(f"✅ Video ID: {result['video_id']}")
            print(f"📝 Title: {result['title']}")
            print(f"🔗 Playable URL: {result['playable_url']}")
            print(f"▶️  Player URL: {result['direct_url']}")
    output = save_results_to_file(all_results)
    print(f"\n💾 Results saved to: {output.absolute()}")
