#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from git import InvalidGitRepositoryError, Repo

load_dotenv(os.path.expanduser("~/.env"))
GITHUB_USERNAME = "unforgivenii147"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_NAME = Path.cwd().name
BRANCH = "main"


def get_or_create_repo():
    try:
        repo = Repo(Path.cwd())
        print("Existing git repository found.")
        return repo
    except InvalidGitRepositoryError:
        print("No git repository found. Creating new one...")
        repo = Repo.init(Path.cwd())
        print("Git repository initialized.")
        return repo


def stage_and_commit(repo):
    if repo.is_dirty(untracked_files=True):
        repo.index.add(["*"])
        repo.index.commit("Update files")
        print("Changes committed.")
    else:
        print("No changes to commit.")


def get_or_create_remote(repo):
    try:
        origin = repo.remote("origin")
        print(f"Remote 'origin' already exists: {origin.url}")
        return origin
    except ValueError:
        print("No remote 'origin' found. Creating GitHub repository...")
        remote_url = create_github_repo()
        origin = repo.create_remote("origin", remote_url)
        print(f"Remote 'origin' created: {remote_url}")
        return origin


def create_github_repo():
    url = "https://api.github.com/user/repos"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    data = {"name": REPO_NAME, "private": False, "auto_init": False}
    response = requests.post(url, headers=headers, data=json.dumps(data))
    if response.status_code == 422:
        print(f"Repository '{REPO_NAME}' may already exist on GitHub.")
        return f"git@github.com:{GITHUB_USERNAME}/{REPO_NAME}.git"
    elif response.status_code != 201:
        raise Exception(f"Failed to create GitHub repo: {response.json()}")
    return response.json()["ssh_url"]


def push_to_github(origin):
    try:
        origin.push(refspec=f"{BRANCH}:{BRANCH}")
        print(f"Successfully pushed to {origin.url}")
    except Exception as e:
        print(f"Push failed: {e}")
        origin.push(refspec=f"{BRANCH}:{BRANCH}", set_upstream=True)


def main():
    if not GITHUB_TOKEN:
        print("Error: GITHUB_TOKEN not found in environment variables.")
        sys.exit(1)
    try:
        repo = get_or_create_repo()
        stage_and_commit(repo)
        origin = get_or_create_remote(repo)
        push_to_github(origin)
        print(f"✅ Repository '{REPO_NAME}' is now on GitHub!")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
