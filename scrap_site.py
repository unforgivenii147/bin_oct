#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://dls2.aparatchi-dlcenter.top/DonyayeSerial/"
OUTPUT_FILE = "movies.txt"
MAX_SIZE_MB = 300
visited = set()
found_movies = []


def size_to_mb(size_str: str) -> float | None:
    match = re.search(r"([\d.]+)\s*Mi?B", size_str)
    if match:
        return float(match.group(1))
    return None


def is_valid_movie(filename: str, size_mb: float | None) -> bool:
    if not filename.lower().endswith(".mkv"):
        return False
    if not ("480p" in filename.lower() or "720p" in filename.lower()):
        return False
    return not (size_mb is None or size_mb >= MAX_SIZE_MB)


def extract_movie_links(soup: BeautifulSoup, page_url: str) -> list[str]:
    movie_links = []
    rows = soup.find_all("tr")
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 3:
            continue
        link_tag = cols[0].find("a")
        if not link_tag:
            continue
        name = link_tag.text.strip()
        href = link_tag.get("href")
        size_text = cols[1].text.strip()
        full_url = urljoin(page_url, href)
        if "Parent directory" in name:
            continue
        if href.endswith("/"):
            crawl(full_url)
        else:
            size_mb = size_to_mb(size_text)
            if is_valid_movie(name, size_mb):
                print(f"  ✓ Found in table: {full_url} ({size_mb} MB)")
                movie_links.append(full_url)
    textareas = soup.find_all("textarea", class_="value")
    for textarea in textareas:
        content = textarea.text.strip()
        if content:
            print(f"  📋 Found textarea with {len(content.splitlines())} links")
            for line in content.splitlines():
                line = line.strip()
                if line.endswith(".mkv") and (
                    "480p" in line.lower() or "720p" in line.lower()
                ):
                    print(f"  ✓ Found in textarea: {line}")
                    movie_links.append(line)
    p_tags = soup.find_all(
        "p", style=lambda value: value and "text-align: center" in value
    )
    for p_tag in p_tags:
        links = p_tag.find_all("a", href=True)
        for link in links:
            href = link.get("href")
            if (
                href
                and href.endswith(".mkv")
                and ("480p" in href.lower() or "720p" in href.lower())
            ):
                print(f"  ✓ Found in p tag: {href}")
                movie_links.append(href)
    return movie_links


def crawl(url: str) -> None:
    if url in visited:
        return
    print(f"\n🔍 Crawling: {url}")
    visited.add(url)
    if "movie" in url:
        return
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        print(f"  📡 Status: {response.status_code}")
    except Exception as e:
        print(f"  ❌ Failed to access {url}: {e}")
        return
    soup = BeautifulSoup(response.text, "html.parser")
    movie_links = extract_movie_links(soup, url)
    for link in movie_links:
        if link not in found_movies:
            found_movies.append(link)
            print(f"  ✅ Added to list: {link}")


if __name__ == "__main__":
    print("🚀 Starting crawler...")
    print(f"📁 Base URL: {BASE_URL}")
    print(f"📊 Max size: {MAX_SIZE_MB} MB")
    print(f"💾 Output file: {OUTPUT_FILE}")
    print("-" * 40)
    crawl(BASE_URL)
    print("\n" + "=" * 40)
    print("✅ Crawling complete!")
    print(f"📈 Total unique movies found: {len(found_movies)}")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.writelines(movie + "\n" for movie in found_movies)
    print(f"💾 Movies saved to: {OUTPUT_FILE}")
    if found_movies:
        print("\n📋 All found movies:")
        for i, movie in enumerate(found_movies, 1):
            print(f"  {i}. {movie}")
    else:
        print("\n⚠️ No movies found matching the criteria!")
