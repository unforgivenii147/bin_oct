#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from git import Repo, exc as GitExc
from github import Github, GithubException

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


def get_repo_info_from_url(url: str) -> tuple[str, str] | None:
    patterns = [
        "https://github\\.com/([^/]+)/([^/]+?)(?:\\.git)?$",
        "git@github\\.com:([^/]+)/([^/]+?)(?:\\.git)?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, url)
        if match:
            return match.group(1), match.group(2)
    return None


def create_new_remote_repo(repo: Repo, github_token: str) -> bool:
    current_dir = Path.cwd()
    repo_name = current_dir.name
    try:
        github = Github(github_token)
        user = github.get_user()
        try:
            existing_repo = user.get_repo(repo_name)
            print(f"Remote repository '{repo_name}' already exists on GitHub.")
            repo.create_remote("origin", existing_repo.clone_url)
            return False
        except GithubException:
            print(f"Creating remote repository '{repo_name}' on GitHub...")
            new_repo = user.create_repo(name=repo_name, private=False, auto_init=False)
            repo.create_remote("origin", new_repo.clone_url)
            print(f"Added remote 'origin': {new_repo.clone_url}")
            return True
    except Exception as e:
        print(f"Failed to create remote repository: {e}", file=sys.stderr)
        sys.exit(1)


def fork_and_update_remote(repo: Repo, github_token: str) -> bool:
    try:
        origin = repo.remote("origin")
        origin_url = origin.url
    except GitExc.NoSuchPathError:
        print("No remote 'origin' found.", file=sys.stderr)
        return False
    repo_info = get_repo_info_from_url(origin_url)
    if not repo_info:
        print(f"Could not parse remote URL: {origin_url}", file=sys.stderr)
        return False
    source_owner, repo_name = repo_info
    if source_owner.lower() == GITHUB_USERNAME.lower():
        print(f"Remote origin is already from your account ({GITHUB_USERNAME}).")
        return False
    try:
        github = Github(github_token)
        user = github.get_user()
        try:
            fork = user.get_repo(repo_name)
            print(f"Fork already exists: {fork.full_name}")
            repo.remote("origin").set_url(fork.clone_url)
            print(f"Updated remote 'origin' to: {fork.clone_url}")
            return False
        except GithubException:
            print(f"Forking {source_owner}/{repo_name} to {GITHUB_USERNAME}...")
            source_repo = github.get_repo(f"{source_owner}/{repo_name}")
            fork = user.create_fork(source_repo)
            print(f"Created fork: {fork.full_name}")
            repo.remote("origin").set_url(fork.clone_url)
            print(f"Updated remote 'origin' to: {fork.clone_url}")
            return True
    except Exception as e:
        print(f"Failed to fork repository: {e}", file=sys.stderr)
        sys.exit(1)


def ensure_remote_repo(repo: Repo, github_token: str) -> bool:
    try:
        repo.remote("origin")
    except GitExc.NoSuchPathError:
        return create_new_remote_repo(repo, github_token)
    try:
        origin = repo.remote("origin")
        if "github.com" in origin.url:
            return fork_and_update_remote(repo, github_token)
    except Exception:
        pass
    return False


def main() -> None:
    repo = ensure_git_repo()
    symlink_global_gitignore()
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN not found in ~/.env", file=sys.stderr)
        sys.exit(1)
    new_remote_created = ensure_remote_repo(repo, token)
    repo.git.add("--all")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_msg = f"Auto-commit at {now}"
    commit_created = False
    try:
        repo.git.commit("-m", commit_msg)
        commit_created = True
    except GitExc.GitCommandError as e:
        if "nothing to commit" in str(e).lower():
            print("No changes to commit.")
        else:
            print(f"Commit failed: {e}", file=sys.stderr)
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
        elif old_url.startswith("git@github.com:"):
            https_url = old_url.replace("git@github.com:", "https://github.com/")
            new_url = https_url.replace(
                "https://github.com/", f"https://{GITHUB_USERNAME}:{token}@github.com/"
            )
            origin.set_url(new_url)
            modified_url = True
        print(f"Pushing to origin/{branch}...")
        if new_remote_created:
            repo.git.push("--set-upstream", "origin", branch)
        else:
            origin.push(refspec=f"{branch}:{branch}")
        if commit_created:
            print(f"Pushed to origin/{branch} with message: {commit_msg}")
        else:
            print(f"Pushed current state to origin/{branch}")
    except GitExc.GitCommandError as e:
        print(f"Push failed: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if modified_url:
            origin.set_url(old_url)


if __name__ == "__main__":
    raise SystemExit(main())
