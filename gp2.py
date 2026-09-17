#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from git import Repo, exc as GitExc

load_dotenv(Path.home() / ".env")
GITHUB_USERNAME = "unforgivenii147"


def ensure_git_repo() -> Repo:
    try:
        return Repo(".")
    except GitExc.InvalidGitRepositoryError:
        print("Not inside a Git repository.", file=sys.stderr)
        sys.exit(1)


def symlink_global_gitignore() -> None:
    home_gitignore = Path.home() / ".gitignore"
    local_gitignore = Path(".gitignore")
    if not home_gitignore.exists():
        print("~/.gitignore does not exist. Create it first if needed.")
        return
    if local_gitignore.exists():
        return
    try:
        local_gitignore.symlink_to(home_gitignore)
        print(f"Symlinked {home_gitignore} -> {local_gitignore}")
    except Exception as e:
        print(f"Failed to create symlink: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    repo = ensure_git_repo()
    symlink_global_gitignore()
    repo.git.add("--all")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_msg = f"Auto-commit at {now}"
    try:
        repo.git.commit("-m", commit_msg)
    except GitExc.GitCommandError:
        print("Nothing to commit (no changes).", file=sys.stderr)
        sys.exit(0)
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN not found in ~/.env", file=sys.stderr)
        sys.exit(1)
    origin = repo.remote("origin")
    old_url = origin.url
    modified_url = False
    try:
        branch = repo.active_branch.name
        if old_url.startswith("https://github.com/"):
            new_url = old_url.replace(
                "https://github.com/", f"https://{GITHUB_USERNAME}:{token}@github.com/"
            )
            origin.set_url(new_url)
            modified_url = True
        print(f"Pushing to origin/{branch}...")
        origin.push(refspec=f"{branch}:{branch}")
        print(f"Pushed to origin/{branch} with message: {commit_msg}")
    except GitExc.GitCommandError as e:
        print(f"Push failed: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if modified_url:
            origin.set_url(old_url)


if __name__ == "__main__":
    raise SystemExit(main())
