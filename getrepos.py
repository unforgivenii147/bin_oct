#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import sys
import threading
import time
from os import getenv
from pathlib import Path

from dotenv import load_dotenv
from github import Auth, Github, GithubException


def countdown(timeout: int) -> None:
    for remaining in range(timeout, 0, -1):
        sys.stdout.write(f"\rTimeout in {remaining:2d} seconds... ")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\r" + " " * 30 + "\r")
    sys.stdout.flush()


def get_repos(username: str, token: str | None = None, timeout: int = 60) -> list:
    countdown_thread = threading.Thread(target=countdown, args=(timeout,), daemon=True)
    countdown_thread.start()
    try:
        if token:
            auth = Auth.Token(token)
            g = Github(auth=auth, timeout=timeout)
        else:
            g = Github(timeout=timeout)
        user = g.get_user(username)
        repos = list(user.get_repos())
        if not repos:
            print(f"\nNo public repositories found for user '{username}'.")
            return []
        return repos
    except GithubException as e:
        if e.status == 404:
            print(f"\nError: User '{username}' not found.")
        elif e.status == 401:
            print("\nError: Invalid or expired token. Check your .env file.")
        elif e.status == 403:
            if "rate limit" in str(e).lower():
                print(
                    "\nError: API rate limit exceeded. Use a token for higher limits."
                )
            else:
                print(f"\nError: Access forbidden. {e.data.get('message', '')}")
        else:
            print(
                f"\nGitHub API Error: {e.status} - {e.data.get('message', 'Unknown error')}"
            )
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: script.py <username>")
        sys.exit(1)
    env_path = Path("~/.env").expanduser()
    load_dotenv(env_path)
    token = getenv("GITHUB_TOKEN")
    username = sys.argv[1]
    if token:
        print("Using authenticated access (rate limit: 5000 requests/hour)")
    else:
        print(
            "No token found in .env, using unauthenticated access (rate limit: 60 requests/hour)"
        )
    repos = get_repos(username, token=token, timeout=60)
    repos.sort(key=lambda r: r.stargazers_count, reverse=True)
    print(f"\nRepositories of '{username}' (sorted by stars):")
    for repo in repos:
        stars = repo.stargazers_count
        language = repo.language or "N/A"
        description = repo.description or "No description"
        print(f"- {repo.name}")
        print(f"  ⭐ {stars} | 🔤 {language} | {description[:80]}")
    json_data = [
        {
            "name": repo.name,
            "stars": repo.stargazers_count,
            "language": repo.language or "N/A",
            "description": repo.description or "No description",
            "url": repo.html_url,
        }
        for repo in repos
    ]
    json_filename = f"{username}.json"
    with Path(json_filename).open("w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=4, ensure_ascii=False)
    print(f"\nData successfully saved to {json_filename}")


if __name__ == "__main__":
    raise SystemExit(main())
