#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from git import InvalidGitRepositoryError, NoSuchPathError, Repo
from github import Github
from github.Auth import Token

env_path = Path.home() / ".env"
load_dotenv(env_path)
GITHUB_USER = "unforgivenii147"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")


def get_dir_name():
    return os.path.basename(os.getcwd())


def copy_gitignore():
    src = Path.home() / ".gitignore"
    dst = Path.cwd() / ".gitignore"
    if src.exists() and not dst.exists():
        shutil.copy2(src, dst)
        print(f"Copied {src} -> {dst}")
    elif dst.exists():
        print(".gitignore already exists in current directory.")
    else:
        print(f"No global .gitignore found at {src}")


def open_repo():
    try:
        return Repo(Path.cwd())
    except (InvalidGitRepositoryError, NoSuchPathError):
        return None


def ensure_local_repo():
    repo = open_repo()
    if repo is None:
        print("Initializing git repository...")
        repo = Repo.init(Path.cwd())
    else:
        print("Git repository already initialized.")
    return repo


def github_client():
    token = GITHUB_TOKEN or os.getenv("GITHUB_TOKEN")
    if not token:
        raise SystemExit("Set GITHUB_TOKEN in the environment.")
    return Github(auth=Token(token))


def repo_exists_on_github(repo_name: str) -> bool:
    g = github_client()
    try:
        user = g.get_user(GITHUB_USER) if GITHUB_USER else g.get_user()
        user.get_repo(repo_name)
        return True
    except Exception:
        return False
    finally:
        g.close()


def ensure_origin(repo: Repo, repo_name: str):
    if "origin" in [r.name for r in repo.remotes]:
        print("Remote 'origin' already exists.")
        return
    if repo_exists_on_github(repo_name):
        print(f"GitHub repo '{repo_name}' already exists on your account.")
        origin_url = f"git@github.com:{repo_name}.git"
        repo.create_remote("origin", origin_url)
        print(f"Added remote origin: {origin_url}")
    else:
        print(f"GitHub repo '{repo_name}' does not exist yet.")
        import subprocess

        cmd = ["gh", "repo", "create", repo_name, "--public", "--source=."]
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error: {result.stderr}")
            sys.exit(1)
        origin_url = f"git@github.com:{repo_name}.git"
        repo.create_remote("origin", origin_url)
        print(f"Added remote origin: {origin_url}")


def commit_if_needed(repo: Repo):
    repo.git.add(all=True)
    if repo.is_dirty(untracked_files=True):
        print("Committing changes...")
        repo.index.commit("initial")
    else:
        print("No changes to commit.")


def push_changes(repo: Repo):
    branch = repo.active_branch.name if not repo.head.is_detached else "main"
    origin = repo.remote("origin")
    print(f"Pushing branch '{branch}'...")
    try:
        origin.push(refspec=f"{branch}:{branch}")
    except Exception as e:
        msg = str(e)
        if "non-fast-forward" in msg or "fetch first" in msg:
            print("Remote has changes. Pulling first...")
            origin.pull(branch, rebase=True)
            print("Pushing again...")
            origin.push(refspec=f"{branch}:{branch}")
        else:
            raise


def main():
    repo_name = get_dir_name()
    print(f"Repository name: {repo_name}")
    copy_gitignore()
    repo = ensure_local_repo()
    ensure_origin(repo, repo_name)
    commit_if_needed(repo)
    push_changes(repo)
    print(f"\n✅ Success! Repository '{repo_name}' is on GitHub or updated there.")
    print(f"View it at: https://github.com/{repo_name}")


if __name__ == "__main__":
    raise SystemExit(main())
