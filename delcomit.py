#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from datetime import datetime, timedelta

from git import Repo


def delete_commits_older_than_week(
    repo_path: str = ".", branch: str = "master"
) -> bool:
    try:
        repo = Repo(repo_path)
        origin = repo.remotes.origin
        upstream = None
        if f"origin/{branch}" in repo.refs:
            upstream = f"origin/{branch}"
        elif branch == "master" and "origin/main" in repo.refs:
            upstream = "origin/main"
            branch = "main"
        else:
            print(f"Error: origin/{branch} not found")
            return False
        print(f"Cleaning commits on {branch} older than one week...")
        current_branch = repo.active_branch
        if current_branch.name != branch:
            if branch in repo.branches:
                repo.head.reference = repo.branches[branch]
            else:
                repo.create_head(branch, repo.refs[upstream])
                repo.head.reference = repo.branches[branch]
            repo.head.reset(index=True, working_tree=True)
        one_week_ago = datetime.now() - timedelta(days=7)
        commits_to_delete = []
        for commit in repo.iter_commits(f"{branch}"):
            commit_date = datetime.fromtimestamp(commit.committed_date)
            if commit_date < one_week_ago and commit not in repo.iter_commits(upstream):
                commits_to_delete.append(commit)
        if not commits_to_delete:
            print("No old commits found to delete")
            return True
        print(f"Found {len(commits_to_delete)} commit(s) to delete:")
        for commit in commits_to_delete[:5]:
            date = datetime.fromtimestamp(commit.committed_date).strftime(
                "%Y-%m-%d %H:%M"
            )
            print(
                f"  {commit.hexsha[:8]} - {date} - {commit.message.splitlines()[0][:50]}"
            )
        oldest_keep = None
        for commit in repo.iter_commits(f"{branch}"):
            commit_date = datetime.fromtimestamp(commit.committed_date)
            if commit_date >= one_week_ago:
                oldest_keep = commit
                break
        if oldest_keep:
            print(f"\nResetting to commit: {oldest_keep.hexsha[:8]}")
            repo.head.reset(oldest_keep, index=True, working_tree=True)
            print("Force pushing cleaned branch...")
            origin.push(refspec=f"{branch}:{branch}", force=True)
            print("Successfully deleted old commits!")
            return True
        else:
            print("No commits to keep found")
            return False
    except Exception as e:
        print(f"Error: {e}")
        return False


def delete_commits_interactive(
    repo_path: str = ".", branch: str = "master", days_old: int = 7
) -> bool:
    try:
        repo = Repo(repo_path)
        origin = repo.remotes.origin
        upstream = f"origin/{branch}"
        if upstream not in repo.refs:
            if branch == "master" and "origin/main" in repo.refs:
                upstream = "origin/main"
                branch = "main"
            else:
                print(f"Error: {upstream} not found")
                return False
        cutoff_date = datetime.now() - timedelta(days=days_old)
        local_commits = []
        for commit in repo.iter_commits(f"{branch}..{upstream}"):
            local_commits.append(commit)
        old_local_commits = []
        for commit in local_commits:
            commit_date = datetime.fromtimestamp(commit.committed_date)
            if commit_date < cutoff_date:
                old_local_commits.append(commit)
        if not old_local_commits:
            print(f"No commits older than {days_old} days found")
            return True
        print(f"\nFound {len(old_local_commits)} commit(s) older than {days_old} days:")
        for i, commit in enumerate(old_local_commits, 1):
            date = datetime.fromtimestamp(commit.committed_date).strftime(
                "%Y-%m-%d %H:%M"
            )
            print(f"{i}. {commit.hexsha[:8]} - {date} - {commit.summary}")
        response = input(f"\nDelete these {len(old_local_commits)} commit(s)? (y/n): ")
        if response.lower() != "y":
            print("Aborted")
            return False
        keep_commit = None
        for commit in repo.iter_commits(f"{upstream}"):
            commit_date = datetime.fromtimestamp(commit.committed_date)
            if commit_date >= cutoff_date:
                keep_commit = commit
                break
        if not keep_commit:
            all_commits = list(repo.iter_commits(upstream))
            if all_commits:
                keep_commit = all_commits[0]
        if keep_commit:
            print(f"\nResetting to: {keep_commit.hexsha[:8]} - {keep_commit.summary}")
            repo.head.reference = repo.branches[branch]
            repo.head.reset(keep_commit, index=True, working_tree=True)
            print("Force pushing to remote...")
            origin.push(refspec=f"{branch}:{branch}", force=True)
            print("Successfully deleted old commits!")
            return True
        else:
            print("Could not find a suitable commit to reset to")
            return False
    except Exception as e:
        print(f"Error: {e}")
        return False


def delete_commits_with_rebase(
    repo_path: str = ".", branch: str = "master", days_old: int = 7
) -> bool | None:
    try:
        repo = Repo(repo_path)
        origin = repo.remotes.origin
        upstream = f"origin/{branch}"
        if (
            upstream not in repo.refs
            and branch == "master"
            and "origin/main" in repo.refs
        ):
            upstream = "origin/main"
            branch = "main"
        if branch not in repo.branches:
            repo.create_head(branch, repo.refs[upstream])
        repo.head.reference = repo.branches[branch]
        cutoff_date = datetime.now() - timedelta(days=days_old)
        first_keep_commit = None
        for commit in repo.iter_commits(f"{branch}"):
            commit_date = datetime.fromtimestamp(commit.committed_date)
            if commit_date >= cutoff_date:
                first_keep_commit = commit
                break
        if not first_keep_commit:
            print("No commits to keep")
            return False
        parent_commit = (
            first_keep_commit.parents[0] if first_keep_commit.parents else None
        )
        if parent_commit:
            print(f"Resetting to parent commit: {parent_commit.hexsha[:8]}")
            repo.head.reset(parent_commit, index=True, working_tree=True)
            commits_to_keep = []
            for commit in repo.iter_commits(f"{first_keep_commit.hexsha}..{branch}"):
                commits_to_keep.append(commit)
            for commit in reversed(commits_to_keep):
                print(f"Applying {commit.hexsha[:8]}...")
                repo.git.cherry_pick(commit.hexsha)
            origin.push(refspec=f"{branch}:{branch}", force=True)
            print("Successfully removed old commits!")
            return True
    except Exception as e:
        print(f"Error: {e}")
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Delete git commits older than one week"
    )
    parser.add_argument("--path", default=".", help="Repository path")
    parser.add_argument("--branch", default="master", help="Branch to clean")
    parser.add_argument(
        "--days", type=int, default=7, help="Delete commits older than N days"
    )
    parser.add_argument("--interactive", action="store_true", help="Interactive mode")
    args = parser.parse_args()
    if args.interactive:
        success = delete_commits_interactive(args.path, args.branch, args.days)
    else:
        success = delete_commits_older_than_week(args.path, args.branch)
    sys.exit(0 if success else 1)
