#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from git import GitCommandError, InvalidGitRepositoryError, Repo


def copy_global_gitignore() -> None:
    home_gitignore = Path.home() / ".gitignore"
    local_gitignore = Path(".gitignore")
    if local_gitignore.exists():
        return
    try:
        data = home_gitignore.read_text(encoding="utf-8")
        local_gitignore.write_text(data, encoding="utf-8")
    except Exception as e:
        return


def main() -> None:
    try:
        repo = Repo(".", search_parent_directories=True)
    except InvalidGitRepositoryError:
        print("Error: Not a git repository.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error accessing repository: {e}", file=sys.stderr)
        sys.exit(1)
    copy_global_gitignore()
    try:
        repo.git.add(A=True)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_msg = f"Auto-commit at {now}"
        repo.index.commit(commit_msg)
        if repo.head.is_detached:
            print(
                "Error: Could not detect current branch (detached HEAD?).",
                file=sys.stderr,
            )
            sys.exit(1)
        branch = repo.active_branch.name
        origin = repo.remote("origin")
        origin.push(branch)
        print(f"Pushed to origin/{branch} with message: {commit_msg}")
    except GitCommandError as e:
        print(f"Git command error: {e}", file=sys.stderr)
        sys.exit(e.status or 1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
