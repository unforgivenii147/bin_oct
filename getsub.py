#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from urllib.parse import quote

import requests


class SubtitleDownloader:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )

    def search_opensubtitles(self, query):
        try:
            search_query = query.replace("_", " ").replace(".", " ")
            url = "https://rest.opensubtitles.com/api/v1/subtitles"
            params = {"query": search_query, "languages": "en", "type": "all"}
            response = self.session.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    for item in data["data"]:
                        attrs = item.get("attributes", {})
                        if attrs.get("language") == "en":
                            return {
                                "id": item["id"],
                                "title": attrs.get("title", query),
                                "url": attrs.get("url"),
                                "files": attrs.get("files", []),
                            }
            return None
        except Exception as e:
            print(f"Error searching OpenSubtitles: {e}")
            return None

    def download_from_opensubtitles(self, sub_info):
        try:
            if sub_info and sub_info.get("files"):
                for file_info in sub_info["files"]:
                    if file_info.get("file_name", "").endswith(".srt"):
                        download_url = file_info.get("url")
                        if download_url:
                            response = self.session.get(download_url)
                            if response.status_code == 200:
                                return response.text
            return None
        except Exception as e:
            print(f"Error downloading from OpenSubtitles: {e}")
            return None

    def search_yify_subtitles(self, query):
        try:
            query = query.replace("_", " ").replace(".", " ")
            search_url = f"https://yts.mx/api/v2/list_movies.json?query_term={quote(query)}&limit=1"
            response = self.session.get(search_url)
            if response.status_code == 200:
                data = response.json()
                movies = data.get("data", {}).get("movies", [])
                if movies:
                    movie_id = movies[0]["id"]
                    subtitle_url = f"https://yts.mx/api/v2/movie_details.json?movie_id={movie_id}&with_images=false"
                    response = self.session.get(subtitle_url)
                    if response.status_code == 200:
                        data = response.json()
                        movie = data.get("data", {}).get("movie", {})
                        subtitles = movie.get("subtitles", [])
                        for sub in subtitles:
                            if sub.get("lang") == "english":
                                return sub.get("url")
            return None
        except Exception as e:
            print(f"Error searching YIFY subtitles: {e}")
            return None

    def download_srt_from_url(self, url):
        try:
            if not url:
                return None
            response = self.session.get(url)
            if response.status_code == 200:
                content = response.text
                if content and ("1\n00:00:" in content or "WEBVTT" in content):
                    return content
                if "application/zip" in response.headers.get("Content-Type", ""):
                    print("ZIP file detected, trying alternative source...")
                    return None
                return content
            return None
        except Exception as e:
            print(f"Error downloading SRT: {e}")
            return None

    def download_subtitles(self, query):
        print(f"Searching for subtitles: {query}")
        print("Trying OpenSubtitles.org...")
        sub_info = self.search_opensubtitles(query)
        if sub_info:
            content = self.download_from_opensubtitles(sub_info)
            if content:
                return content, "OpenSubtitles.org"
        print("Trying YIFY subtitles...")
        sub_url = self.search_yify_subtitles(query)
        if sub_url:
            content = self.download_srt_from_url(sub_url)
            if content:
                return content, "YIFY Subtitles"
        return None, None

    def save_subtitle(self, content, filename):
        if not content:
            return False
        filename = re.sub(r"[^\w\s-]", "", filename)
        filename = re.sub(r"[-\s]+", "_", filename)
        if not filename.endswith(".srt"):
            filename += ".srt"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"✅ Subtitle saved to: {filename}")
            return True
        except Exception as e:
            print(f"Error saving file: {e}")
            return False


def main():
    if len(sys.argv) < 2:
        print('Usage: python get_sub.py "movie_or_series_name"')
        print("Example: python get_sub.py outcast_s01")
        print('Example: python get_sub.py "The Witcher season 2"')
        sys.exit(1)
    query = " ".join(sys.argv[1:])
    downloader = SubtitleDownloader()
    content, source = downloader.download_subtitles(query)
    if content:
        print(f"✅ Subtitles found from {source}")
        filename = query.replace(" ", "_").replace(".", "_")
        downloader.save_subtitle(content, filename)
    else:
        print("❌ No subtitles found for the given query")
        print("Tips:")
        print("  - Try using the exact movie/TV show name")
        print("  - For TV series, use format: 'show_name_season_episode'")
        print("  - Example: 'breaking_bad_s01e01'")
        print("  - Try removing special characters")


if __name__ == "__main__":
    raise SystemExit(main())
