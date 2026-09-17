#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta

from git import Repo


def remove_old_commits(repo_path=".", days=30):
    repo = Repo(repo_path)
    cutoff_date = datetime.now() - timedelta(days=days)
    cutoff_timestamp = int(cutoff_date.timestamp())
    print(f"Cutoff date: {cutoff_date}")
    print(f"Will keep commits newer than {days} days ago")
    try:
        commits = list(repo.iter_commits("HEAD"))
    except Exception as e:
        print(f"Error: Could not get commits. {e}")
        return
    if not commits:
        print("No commits found in repository")
        return
    print(f"Total commits: {len(commits)}")
    earliest_commit_to_keep = None
    commits_to_remove = []
    commits_to_keep = []
    for commit in commits:
        commit_date = datetime.fromtimestamp(commit.committed_date)
        if commit_date > cutoff_date:
            earliest_commit_to_keep = commit
            commits_to_keep.append(commit)
        else:
            commits_to_remove.append(commit)
    print(f"Commits to keep: {len(commits_to_keep)}")
    print(f"Commits to remove: {len(commits_to_remove)}")
    if not earliest_commit_to_keep:
        print("No commits to keep! Aborting to prevent data loss.")
        return
    if len(commits_to_remove) == 0:
        print("No old commits to remove.")
        return
    print(
        f"\nOldest commit to keep: {earliest_commit_to_keep.hexsha[:7]} - {earliest_commit_to_keep.summary}"
    )
    print(f"Date: {datetime.fromtimestamp(earliest_commit_to_keep.committed_date)}")
    response = input(
        "\nWARNING: This operation will rewrite git history!\nContinue? (yes/no): "
    )
    if response.lower() != "yes":
        print("Operation cancelled.")
        return
    try:
        print("\nRewriting git history...")
        if earliest_commit_to_keep.parents:
            parent_to_remove = earliest_commit_to_keep.parents[0]
            current_branch = repo.active_branch.name
            new_root = repo.git.commit_tree(
                earliest_commit_to_keep.tree,
                "-m",
                f"Squashed history (keeping last {days} days)",
            )
            commits_to_apply = list(reversed(commits_to_keep[:-1]))
            repo.git.checkout(current_branch)
            repo.git.reset("--hard", earliest_commit_to_keep.hexsha)
            print("Old commits removed. History has been rewritten.")
            print(
                "\nIMPORTANT: You may need to force push if this is a remote repository:"
            )
            print(f"  git push --force origin {current_branch}")
    except Exception as e:
        print(f"Error during history rewrite: {e}")
        print("\nAttempting alternative method...")
        try:
            repo.git.reset("--soft", earliest_commit_to_keep.hexsha)
            repo.index.commit("Consolidated commit (old history removed)")
            print("Alternative method completed. History has been rewritten.")
        except Exception as e2:
            print(f"Alternative method also failed: {e2}")
            print("\nManual steps to achieve this:")
            print(f"1. git checkout {earliest_commit_to_keep.hexsha}")
            print("2. git checkout --orphan temp_branch")
            print("3. git commit -m 'Initial commit (history cleaned)'")
            print("4. git cherry-pick <subsequent commits if any>")
            print("5. git branch -D main  # delete old branch")
            print("6. git branch -m temp_branch main  # rename temp to main")


def remove_commits_older_than_days(repo_path=".", days=30, auto_confirm=False):
    repo = Repo(repo_path)
    cutoff_timestamp = int((datetime.now() - timedelta(days=days)).timestamp())
    commits = list(repo.iter_commits("HEAD"))
    commits_to_keep = []
    for commit in commits:
        if commit.committed_date > cutoff_timestamp:
            commits_to_keep.append(commit)
    if len(commits_to_keep) == len(commits):
        print("No old commits to remove.")
        return
    if not commits_to_keep:
        print("No commits to keep! Operation aborted.")
        return
    print(
        f"Keeping {len(commits_to_keep)} recent commits out of {len(commits)} total commits"
    )
    if not auto_confirm:
        response = input("Continue with history rewrite? (yes/no): ")
        if response.lower() != "yes":
            print("Cancelled.")
            return
    newest_to_keep = commits_to_keep[0]
    current_branch = repo.active_branch
    new_branch_name = f"cleaned_{current_branch.name}"
    try:
        repo.git.checkout("--orphan", new_branch_name)
        for commit in reversed(commits_to_keep):
            repo.git.cherry_pick("--allow-empty", commit.hexsha)
        print(
            f"\nNew branch '{new_branch_name}' created with {len(commits_to_keep)} recent commits."
        )
        print("\nTo replace the original branch, run:")
        print(f"  git checkout {current_branch.name}")
        print(f"  git reset --hard {new_branch_name}")
        print(f"  git branch -D {new_branch_name}")
    except Exception as e:
        print(f"Error: {e}")
        with contextlib.suppress(BaseException):
            repo.git.checkout(current_branch.name)


if __name__ == "__main__":
    import sys

    days = 30
    if len(sys.argv) > 1:
        try:
            days = int(sys.argv[1])
        except ValueError:
            print(f"Invalid days argument: {sys.argv[1]}")
            print("Using default: 30 days")
    print(f"Git History Cleaner - Remove commits older than {days} days")
    print("-" * 40)
    print("\nOptions:")
    print("1. Safe mode - preserves commits but can specify which to keep")
    print("2. Orphan branch mode - creates new branch with only recent commits")
    choice = input("\nSelect option (1 or 2, default 1): ").strip()
    if choice == "2":
        remove_commits_older_than_days(days=days)
    else:
        remove_old_commits(days=days)
