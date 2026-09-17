#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import os
import re
import sys
from argparse import Namespace
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from git import InvalidGitRepositoryError, Repo


def parse_arguments() -> Namespace:
    parser = argparse.ArgumentParser(
        description="Commit and push all files to git repository"
    )
    parser.add_argument(
        "-c",
        "--create",
        action="store_true",
        help="Create remote repository on GitHub if it doesn't exist",
    )
    parser.add_argument(
        "-r",
        "--remote-name",
        default="origin",
        help="Remote name to use (default: origin)",
    )
    return parser.parse_args()


def load_git_token() -> str | None:
    env_path = Path.home() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        return None
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or os.getenv("GIT_TOKEN")
    return token


def create_github_repo(
    repo_name: str, description: str = "new git repo", private: bool = False
):
    token = load_git_token()
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    data = {
        "name": repo_name,
        "description": description,
        "private": private,
        "auto_init": True,
    }
    response = requests.post(
        "https://api.github.com/user/repos", json=data, headers=headers
    )
    if response.status_code == 201:
        return response.json()["html_url"]
    else:
        raise Exception(f"GitHub API error: {response.json().get('message')}")


def get_github_username(token: str) -> str | None:
    try:
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        response = requests.get("https://api.github.com/user", headers=headers)
        if response.status_code == 200:
            return response.json()["login"]
        else:
            print(f"Failed to get GitHub username: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error getting GitHub username: {e}")
        return None


def get_cwd_name() -> str:
    dir_name = Path.cwd().name
    dir_name = re.sub(r"[^\w\-\.]", "-", dir_name)
    return dir_name.lower()


def setup_remote_repo(
    repo: Repo, token: str, remote_name: str, create_if_missing: bool
) -> bool:
    existing_remote = None
    try:
        if remote_name in [r.name for r in repo.remotes]:
            existing_remote = repo.remote(remote_name)
            try:
                list(existing_remote.urls)
                print(
                    f"Remote '{remote_name}' already configured: {existing_remote.url}"
                )
                return True
            except Exception:
                print(f"⚠️ Remote '{remote_name}' has invalid URL, removing...")
                repo.delete_remote(existing_remote)
                existing_remote = None
    except Exception:
        pass
    repo_name = get_cwd_name()
    if not create_if_missing:
        return False
    is_private = False
    try:
        description = "Repository description"
        clone_url = create_github_repo(repo_name, description, is_private)
        print(f"Adding remote '{remote_name}': {clone_url}")
        repo.create_remote(remote_name, clone_url)
        return True
    except Exception as e:
        print(f"❌ Failed to create repository: {e}")
        return False


def setup_git_auth(repo: Repo, token: str | None = None) -> None:
    if not token:
        return
    try:
        for remote in repo.remotes:
            for url in remote.urls:
                if "github.com" in url:
                    if "@github.com" in url:
                        print("Remote URL already has authentication")
                        return
                    elif url.startswith("https://"):
                        new_url = url.replace("https://", f"https://oauth2:{token}@")
                        remote.set_url(new_url)
                        print("✅ Updated remote URL with token authentication")
                        return
                    elif url.startswith("git@github.com:"):
                        print("Using SSH authentication (no token needed)")
                        return
    except Exception as e:
        print(f"Could not update remote URL: {e}")


def push_to_remote(repo: Repo, remote_name: str, token: str = load_git_token()) -> None:
    try:
        if remote_name not in [r.name for r in repo.remotes]:
            print(f"❌ Remote '{remote_name}' not configured. Skipping push.")
            return
        remote = repo.remote(remote_name)
        try:
            current_branch = repo.active_branch.name
        except TypeError:
            print("In detached HEAD state. Skipping push.")
            return
        print(f"\n📤 Pushing to remote '{remote_name}'...")
        if token:
            setup_git_auth(repo, token)
        try:
            push_result = remote.push(
                refspec=f"{current_branch}:{current_branch}", set_upstream=True
            )
        except Exception as e:
            if "no upstream branch" in str(e):
                print("Setting upstream and pushing...")
                repo.git.push("--set-upstream", remote_name, current_branch)
                push_result = []
            else:
                raise
        success = False
        if push_result:
            for result in push_result:
                if hasattr(result, "flags") and result.flags & result.ERROR:
                    print(f"❌ Push failed: {result.summary}", file=sys.stderr)
                    if "403" in result.summary or "401" in result.summary:
                        print(
                            "🔐 Authentication failed. Check your GitHub token.",
                            file=sys.stderr,
                        )
                    return
                elif hasattr(result, "flags") and result.flags & result.UP_TO_DATE:
                    print("✅ Remote is already up to date.")
                    success = True
                elif hasattr(result, "flags") and result.flags & result.FAST_FORWARD:
                    print(f"✅ Successfully pushed to {remote_name}/{current_branch}")
                    success = True
                else:
                    print("✅ Push successful")
                    success = True
        else:
            success = True
            print(f"✅ Successfully pushed to {remote_name}/{current_branch}")
        if success:
            print("\n🎉 All done! Changes are now on GitHub.")
    except Exception as e:
        print(f"❌ Push failed: {e}", file=sys.stderr)
        print("Commit was successful, but push failed. You can push manually later.")


def main() -> None:
    args = parse_arguments()
    token = load_git_token()
    cwd = Path.cwd()
    repo = None
    try:
        repo = Repo(cwd, search_parent_directories=True)
        print(f"Found existing git repository at {repo.git_dir}")
    except InvalidGitRepositoryError:
        repo = Repo.init(cwd)
        print("✅ Repository initialized.")
    if not repo.remotes or args.create:
        if setup_remote_repo(repo, token, args.remote_name, args.create):
            print("✅ Remote repository configured")
        elif not args.create:
            pass
    if not repo.is_dirty(untracked_files=True):
        print("\n📝 No changes to commit.")
        if repo.remotes:
            try:
                current_branch = repo.active_branch
                remote_name = args.remote_name
                if remote_name in [r.name for r in repo.remotes]:
                    repo.remote(remote_name)
                    try:
                        remote_ref = f"refs/remotes/{remote_name}/{current_branch.name}"
                        if remote_ref in repo.refs:
                            remote_commit = repo.refs[remote_ref].commit
                            if current_branch.commit != remote_commit:
                                print("Found unpushed commits. Pushing...")
                                push_to_remote(repo, remote_name, token)
                            else:
                                print("✅ Remote is up to date.")
                        else:
                            print("Remote branch doesn't exist. Pushing...")
                            push_to_remote(repo, remote_name, token)
                    except Exception as e:
                        print(f"Remote exists but check failed: {e}")
                        push_to_remote(repo, remote_name, token)
                else:
                    print(f"Remote '{remote_name}' not found.")
            except Exception as e:
                print(f"Push check failed: {e}")
        return
    print("\n📦 Changes detected. Adding all files...")
    repo.git.add("--all")
    commit_message = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        commit = repo.index.commit(commit_message)
        print(f'✅ Committed with message: "{commit_message}"')
        print(f"Commit hash: {commit.hexsha[:7]}")
    except Exception as e:
        print(f"❌ Commit failed: {e}", file=sys.stderr)
        sys.exit(1)
    if repo.remotes and args.remote_name in [r.name for r in repo.remotes]:
        push_to_remote(repo, args.remote_name, token)
    elif repo.remotes:
        print(f"""
⚠️ Remote '{args.remote_name}' not found. Available remotes: {[r.name for r in repo.remotes]}""")
        print("Changes committed locally only.")
    else:
        print("\n⚠️ No remote configured. Changes committed locally only.")
        if args.create:
            print("Use --create flag to create and push to GitHub.")


if __name__ == "__main__":
    raise SystemExit(main())
