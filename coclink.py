#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import Resource, build

load_dotenv()
API_KEY = os.getenv("YOUTUBE_API_KEY")
CHANNELS = {
    "Blueprint_CoC": "UCQJJGSWnPUCb8uKV_MoJeOA",
    "iTzu": "UCLKKvlo0yK8OgWvjCiZQ3sA",
    "Clash_Champs": "UC_mD8S6pWpSstY3mXJ9nEqw",
}


def get_videos(youtube: Resource, channel_id: str):
    past_date = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    videos = []
    request = youtube.search().list(
        part="snippet",
        channelId=channel_id,
        publishedAfter=past_date,
        maxResults=50,
        order="date",
        type="video",
    )
    while request:
        response = request.execute()
        for item in response.get("items", []):
            video_id = item["id"]["videoId"]
            video_details = youtube.videos().list(part="snippet", id=video_id).execute()
            snippet = video_details["items"][0]["snippet"]
            videos.append(
                {
                    "title": snippet["title"],
                    "description": snippet["description"],
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                }
            )
        request = youtube.search().list_next(request, response)
        if len(videos) > 100:
            break
    return videos


def extract_th18_links(description):
    pattern = "(https?://link\\.clashofclans\\.com/[^\\s]+)"
    links = re.findall(pattern, description)
    return [l for l in links if "TH18" in l.upper() or "TH18" in description.upper()]


def create_html(channel_name: str, base_data) -> None:
    date_str = datetime.now().strftime("%d-%m-%Y")
    dir_path = Path(f"output/{date_str}_{channel_name}")
    dir_path.mkdir(exist_ok=True, parents=True)
    path = dir_path / "bases.html"
    html_content = f"""
    <html>
    <head>
        <title>{channel_name} TH18 Bases</title>
        <style>
            body {{ font-family: sans-serif; padding: 20px; background:
            .card {{ background: white; margin-bottom: 15px; padding: 15px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            a {{ color:
            .vid-ref {{ font-size: 0.9em; color:
        </style>
    </head>
    <body>
        <h1>TH18 Bases from {channel_name} (Last 30 Days)</h1>
    """
    for item in base_data:
        html_content += f"""
        <div class="card">
            <h3>{item["title"]}</h3>
            <p class="vid-ref">Source: <a href="{item["video_url"]}" target="_blank">Watch Video</a></p>
            <ul>
        """
        for link in item["links"]:
            html_content += f'<li><a href="{link}">Get Base Layout</a></li>'
        html_content += "</ul></div>"
    html_content += "</body></html>"
    path.write_text(html_content, encoding="utf-8")
    print(f"Generated: {path}")


def main() -> None:
    if not API_KEY:
        print("Error: API_KEY not found in .env file.")
        return
    youtube = build("youtube", "v3", developerKey=API_KEY)
    for name, cid in CHANNELS.items():
        print(f"Processing {name}...")
        vids = get_videos(youtube, cid)
        results = []
        for v in vids:
            links = extract_th18_links(v["description"])
            if links:
                results.append(
                    {
                        "title": v["title"],
                        "video_url": v["url"],
                        "links": list(set(links)),
                    }
                )
        if results:
            create_html(name, results)
        else:
            print(f"No TH18 links found for {name}.")


if __name__ == "__main__":
    raise SystemExit(main())
