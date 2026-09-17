#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
from pathlib import Path


def is_git_repo(path: Path) -> bool:
    return (path / ".git").is_dir()


def git_pull(repo_path: Path) -> None:
    print(f"\n==> Pulling in repo: {repo_path}")
    try:
        subprocess.run(["git", "-C", str(repo_path), "pull", "--ff-only"], check=True)
    except subprocess.CalledProcessError:
        print(f"⚠️  git pull failed in: {repo_path}")


def walk_and_pull(path: Path) -> None:
    if is_git_repo(path):
        git_pull(path)
        return
    try:
        for item in path.iterdir():
            if item.is_dir() and item.name != ".git":
                walk_and_pull(item)
    except PermissionError:
        pass


def main() -> None:
    root = Path.cwd()
    walk_and_pull(root)
    print("\nDone.")


if __name__ == "__main__":
    raise SystemExit(main())
