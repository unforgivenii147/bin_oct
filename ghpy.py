#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import load_dotenv


def search_python_repos():
    load_dotenv(Path.home() / ".env")
    token = os.getenv("GITHUB_TOKEN")
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "q": "language:Python",
        "sort": "updated",
        "order": "desc",
        "per_page": 50,
    }
    response = requests.get(
        "https://api.github.com/search/repositories", headers=headers, params=params
    )
    response.raise_for_status()
    data = response.json()
    output = Path("ghpy.txt")
    with output.open("w") as f:
        f.write("50 most active py repos\n")
        f.write("=" * 40 + "\n\n")
        for repo in data["items"]:
            f.write(f"{repo['full_name']}\n")
            f.write(f"  URL: {repo['html_url']}\n")
            f.write(f"  Updated: {repo['updated_at']}\n")
            f.write(f"  Stars: {repo['stargazers_count']}\n\n")
    print(f"Results saved to {output}")


if __name__ == "__main__":
    search_python_repos()
