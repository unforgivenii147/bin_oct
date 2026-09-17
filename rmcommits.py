#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

import git
from git import GitCommandError, Repo


def delete_old_commits(days: int) -> None:
    try:
        repo = Repo(".")
        if repo.head.is_detached:
            print("Error: HEAD is detached. Please checkout a branch first.")
            sys.exit(1)
        current_branch = repo.active_branch.name
        print(f"Current branch: {current_branch}")
        cutoff_date = datetime.now(UTC) - timedelta(days=days)
        print(f"Cutoff date: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        if repo.is_dirty(untracked_files=True):
            print(
                "Error: Working directory is not clean. Please commit or stash changes."
            )
            sys.exit(1)
        commits = list(repo.iter_commits(current_branch))
        if not commits:
            print("No commits found in repository.")
            return
        commits_to_keep = []
        commits_to_delete = []
        for commit in commits:
            commit_date = commit.committed_datetime.replace(tzinfo=UTC)
            if commit_date > cutoff_date:
                commits_to_keep.append(commit)
            else:
                commits_to_delete.append(commit)
        if not commits_to_delete:
            print(f"No commits older than {days} days found.")
            return
        if not commits_to_keep:
            print(
                "Error: All commits would be deleted. At least one commit must remain."
            )
            sys.exit(1)
        print(
            f"\nFound {len(commits_to_delete)} commits to delete (older than {days} days)"
        )
        print(f"Keeping {len(commits_to_keep)} commits")
        preview_count = min(5, len(commits_to_delete))
        print("\nPreview of commits to delete (oldest first):")
        for commit in commits_to_delete[-preview_count:]:
            commit_date = commit.committed_datetime.replace(tzinfo=UTC)
            print(
                f"  {commit.hexsha[:8]} - {commit_date.strftime('%Y-%m-%d %H:%M')} - {commit.summary}"
            )
        if len(commits_to_delete) > preview_count:
            print(f"  ... and {len(commits_to_delete) - preview_count} more")
        new_head_commit = commits_to_keep[0]
        print(
            f"\nNew HEAD will be: {new_head_commit.hexsha[:8]} - {new_head_commit.summary}"
        )
        response = input("""
This operation will PERMANENTLY DELETE these commits. Continue? (yes/no): """)
        if response.lower() != "yes":
            print("Operation cancelled.")
            return
        backup_branch = (
            f"backup-{current_branch}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        )
        print(f"\nCreating backup branch: {backup_branch}")
        repo.create_head(backup_branch)
        print(f"Resetting {current_branch} to {new_head_commit.hexsha[:8]}...")
        repo.git.reset("--hard", new_head_commit.hexsha)
        print(
            f"\nSuccessfully deleted {len(commits_to_delete)} commits older than {days} days."
        )
        print(f"Backup branch '{backup_branch}' contains the original commits.")
        print("""
NOTE: If you've already pushed the old commits to a remote, you'll need to force push:""")
        print(f"  git push --force origin {current_branch}")
        print("\nTo restore the original commits:")
        print(f"  git reset --hard {backup_branch}")
    except git.InvalidGitRepositoryError:
        print("Error: Current directory is not a Git repository.")
        sys.exit(1)
    except GitCommandError as e:
        print(f"Git command error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python script.py <days>")
        print("Example: python script.py 30  (deletes commits older than 30 days)")
        sys.exit(1)
    try:
        days = int(sys.argv[1])
        if days < 1:
            print("Error: Number of days must be positive.")
            sys.exit(1)
    except ValueError:
        print("Error: Please provide a valid integer for days.")
        sys.exit(1)
    print("Git Commit Cleanup Tool")
    print("=======================")
    print(f"Will delete commits older than {days} days")
    print(f"Current time (UTC): {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')}")
    delete_old_commits(days)


if __name__ == "__main__":
    raise SystemExit(main())
