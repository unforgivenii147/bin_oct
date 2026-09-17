#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv


def search_github_repos() -> None:
    env_path = Path.home() / ".env"
    load_dotenv(env_path)
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError(f"GITHUB_TOKEN not found in {env_path}")
    date_10_days_ago = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    query = f"language:Python created:>{date_10_days_ago}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {token}",
    }
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": 50}
    response = requests.get(
        "https://api.github.com/search/repositories", headers=headers, params=params
    )
    response.raise_for_status()
    data = response.json()
    output_file = Path("ghpy10.txt")
    with output_file.open("w") as f:
        for repo in data["items"]:
            f.write(f"{repo['full_name']} - {repo['stargazers_count']} stars\n")
    print(f"✓ Saved {len(data['items'])} repos to ghpy10.txt")


if __name__ == "__main__":
    search_github_repos()
