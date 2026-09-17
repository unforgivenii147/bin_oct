#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import subprocess
import sys


def run_command(cmd, check=True):
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"Error: {result.stderr}")
        sys.exit(1)
    return result


def is_git_repo():
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"], capture_output=True, text=True
    )
    return result.returncode == 0


def get_dir_name():
    return os.path.basename(os.getcwd())


def main():
    repo_name = get_dir_name()
    print(f"Repository name: {repo_name}")
    if not is_git_repo():
        print("Initializing git repository...")
        run_command(["git", "init"])
    else:
        print("Git repository already initialized.")
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Creating GitHub repository '{repo_name}'...")
        run_command(["gh", "repo", "create", repo_name, "--public", "--source=."])
    else:
        print("Remote 'origin' already exists. Checking if repo exists on GitHub...")
        fetch_result = subprocess.run(
            ["git", "fetch", "origin"], capture_output=True, text=True
        )
        if fetch_result.returncode == 0:
            print("GitHub repository exists. Will push changes.")
        else:
            print(
                "Remote exists but seems inaccessible. You might need to authenticate."
            )
            print(f"Remote URL: {result.stdout.strip()}")
    print("Adding all files...")
    run_command(["git", "add", "-A"])
    status = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True
    )
    if status.stdout.strip():
        print("Committing changes...")
        run_command(["git", "commit", "-m", "initial"])
    else:
        print("No changes to commit.")
    print("Pushing to GitHub...")
    branch_result = subprocess.run(
        ["git", "branch", "--show-current"], capture_output=True, text=True
    )
    current_branch = (
        branch_result.stdout.strip() if branch_result.returncode == 0 else "main"
    )
    push_result = subprocess.run(
        ["git", "push", "--set-upstream", "origin", current_branch],
        capture_output=True,
        text=True,
    )
    if push_result.returncode != 0:
        if "remote contains work that you do not have" in push_result.stderr:
            print("Remote has changes. Pulling first...")
            run_command(["git", "pull", "origin", current_branch, "--rebase"])
            print("Pushing again...")
            run_command(["git", "push", "--set-upstream", "origin", current_branch])
        else:
            print(f"Push failed: {push_result.stderr}")
            sys.exit(1)
    print(f"\n✅ Success! Repository '{repo_name}' is now on GitHub.")
    print(f"View it at: https://github.com/{repo_name}")


if __name__ == "__main__":
    raise SystemExit(main())
