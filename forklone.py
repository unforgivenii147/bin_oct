#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from git import Repo
from github import Github
from github.GithubException import GithubException, UnknownObjectException


def load_env_token():
    env_path = Path.home() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        token = os.getenv("GITHUB_TOKEN")
        if token:
            print(f"✓ Loaded GITHUB_TOKEN from {env_path}")
            return token
        else:
            print(f"⚠️  {env_path} exists but GITHUB_TOKEN not found")
    else:
        print("⚠️  ~/.env file not found")
    return None


def get_github_client():
    token = load_env_token()
    if not token:
        print("\nGitHub token required")
        print("Please add to ~/.env file:")
        print("GITHUB_TOKEN=your_token_here")
        print("\nOr set environment variable:")
        print("  export GITHUB_TOKEN=your_token_here")
        print("\nGet a token at: https://github.com/settings/tokens")
        print("Required scope: 'repo' for private repos or 'public_repo' for public")
        sys.exit(1)
    try:
        g = Github(token)
        user = g.get_user()
        print(f"✓ Authenticated as: {user.login}")
        return g, user
    except GithubException as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)


def fork_repository(g, user, repo_full):
    try:
        original_repo = g.get_repo(repo_full)
        print(f"✓ Found original repo: {original_repo.full_name}")
        try:
            forked_repo = user.get_repo(original_repo.name)
            print(f"✓ Repository already forked: {forked_repo.clone_url}")
            return forked_repo
        except UnknownObjectException:
            print(f"Forking {repo_full}...")
            forked_repo = original_repo.create_fork()
            print(f"✓ Fork created: {forked_repo.clone_url}")
            return forked_repo
    except GithubException as e:
        print(f"Error forking repository: {e}")
        sys.exit(1)


def clone_and_setup(forked_repo, original_full_name):
    repo_name = forked_repo.name
    clone_url = forked_repo.clone_url
    print(f"\nCloning {clone_url}...")
    try:
        local_repo = Repo.clone_from(clone_url, repo_name)
        print(f"✓ Cloned to: ./{repo_name}")
    except Exception as e:
        print(f"Error cloning: {e}")
        sys.exit(1)
    upstream_url = f"https://github.com/{original_full_name}.git"
    print(f"Adding upstream remote: {upstream_url}")
    upstream = local_repo.create_remote("upstream", upstream_url)
    default_branch = forked_repo.default_branch
    print("Fetching from upstream...")
    upstream.fetch()
    local_repo.git.branch(
        f"--set-upstream-to=upstream/{default_branch}", default_branch
    )
    return local_repo, default_branch


def create_env_template():
    env_path = Path.home() / ".env"
    if not env_path.exists():
        print("\n📝 Creating ~/.env template...")
        with open(env_path, "w") as f:
            f.write("# GitHub Personal Access Token\n")
            f.write("# Get one at: https://github.com/settings/tokens\n")
            f.write("# Required scopes: repo, public_repo\n")
            f.write("GITHUB_TOKEN=your_token_here\n")
        print(f"✓ Created {env_path}")
        print("⚠️  Please edit the file and add your actual token")
        return False
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py user/repo")
        print("Example: python script.py octocat/Hello-World")
        print("\nAlso supports full GitHub URLs:")
        print("  python script.py https://github.com/user/repo")
        sys.exit(1)
    repo_input = sys.argv[1]
    if repo_input.startswith("https://github.com/"):
        repo_full = repo_input.replace("https://github.com/", "").rstrip("/")
    else:
        repo_full = repo_input
    if "/" not in repo_full:
        print("Error: Use format 'user/repo'")
        print("Example: octocat/Hello-World")
        sys.exit(1)
    create_env_template()
    g, user = get_github_client()
    forked_repo = fork_repository(g, user, repo_full)
    local_repo, default_branch = clone_and_setup(forked_repo, repo_full)
    print("\n✓ Setup complete!")
    print("\nRemotes configured:")
    for remote in local_repo.remotes:
        print(f"  {remote.name}: {remote.url}")
    print(f"\nTo pull from original repo: git pull upstream {default_branch}")
    print(f"To push to your fork: git push origin {default_branch}")
    print(f"\nRepo location: ./{forked_repo.name}")
    print("\nRepository info:")
    print(f"  Original: {repo_full}")
    print(f"  Your fork: {forked_repo.full_name}")
    print(f"  Default branch: {default_branch}")


if __name__ == "__main__":
    raise SystemExit(main())
