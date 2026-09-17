#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
from pathlib import Path

import git
from dotenv import load_dotenv
from github import Github, GithubException


def setup_github_client():
    env_path = Path.home() / ".env"
    if not env_path.exists():
        raise FileNotFoundError(f"Could not find .env file at {env_path}")
    load_dotenv(dotenv_path=env_path)
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN not found in ~/.env")
    return (Github(token), token)


def get_repo_info(repo: git.Repo):
    try:
        remote_url = repo.remotes.origin.url
        remote_url = remote_url.removesuffix(".git")
        if "github.com" in remote_url:
            parts = remote_url.split("github.com")[-1].strip("/:").split("/")
            if len(parts) >= 2:
                return (parts[0], parts[1])
    except (AttributeError, IndexError):
        pass
    raise ValueError("Could not parse a valid GitHub remote URL from 'origin'.")


def main():
    try:
        local_dir = os.getcwd()
        local_repo = git.Repo(local_dir, search_parent_directories=True)
        g, token = setup_github_client()
        current_user = g.get_user()
        my_username = current_user.login
        repo_owner, repo_name = get_repo_info(local_repo)
        print(f"[*] Local repo detected: {repo_owner}/{repo_name}")
        print(f"[*] Authenticated as GitHub user: {my_username}")
        print("[*] Fetching updates from remote...")
        origin = local_repo.remotes.origin
        origin.fetch()
        active_branch = local_repo.active_branch
        if not active_branch.tracking_branch():
            print(
                f"[!] Active branch '{
                    active_branch.name
                }' has no upstream tracking branch. Setting to origin/{
                    active_branch.name
                }"
            )
            active_branch.set_tracking_branch(origin.refs[active_branch.name])
        print(f"[*] Pulling latest changes into '{active_branch.name}'...")
        origin.pull()
        if repo_owner.lower() == my_username.lower():
            print(
                "[+] You are the owner of this repository. Preparing to push local changes..."
            )
            if local_repo.is_dirty(untracked_files=True):
                print(
                    "[-] Found uncommitted local changes. Please commit them before pushing."
                )
                return
            print(f"[*] Pushing '{active_branch.name}' to origin...")
            info = origin.push()
            if info[0].flags & git.remote.PushInfo.ERROR:
                print(f"[-] Push failed: {info[0].summary}")
            else:
                print("[+] Successfully synced and pushed updates to your repository!")
        else:
            print("[*] You are not the owner. Checking for fork status...")
            target_repo = g.get_repo(f"{repo_owner}/{repo_name}")
            try:
                my_fork = current_user.get_repo(repo_name)
                print(f"[+] Existing fork found: {my_fork.full_name}")
            except GithubException as e:
                if e.status == 404:
                    print(
                        f"[*] Creating a fork of {repo_owner}/{repo_name} on your account..."
                    )
                    my_fork = current_user.create_fork(target_repo)
                    print(f"[+] Fork created successfully: {my_fork.full_name}")
                else:
                    raise
            fork_url = f"https://{my_username}:{token}@github.com/{my_username}/{repo_name}.git"
            if "fork" in local_repo.remotes:
                fork_remote = local_repo.remotes.fork
                fork_remote.set_url(fork_url)
            else:
                print("[*] Adding 'fork' remote to local configuration...")
                fork_remote = local_repo.create_remote("fork", fork_url)
            print(f"[*] Pushing '{active_branch.name}' to your fork...")
            fork_info = fork_remote.push(
                refspec=f"{active_branch.name}:{active_branch.name}"
            )
            if fork_info[0].flags & git.remote.PushInfo.ERROR:
                print(f"[-] Push to fork failed: {fork_info[0].summary}")
            else:
                print(
                    "[+] Successfully pulled upstream updates and pushed your work to your fork!"
                )
    except git.InvalidGitRepositoryError:
        print("[-] Error: Current directory is not inside a valid Git repository.")
    except Exception as e:
        print(f"[-] An error occurred: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
