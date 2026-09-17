#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def is_git_repo(path: Path) -> bool:
    return (path / ".git").is_dir()


def git_pull(repo_path: Path) -> None:
    print(f"\n==> Pulling in repo: {repo_path}")
    try:
        subprocess.run(["git", "-C", str(repo_path), "restore", "."], check=True)
    except subprocess.CalledProcessError:
        print(f"⚠️  git pull failed in: {repo_path}")


def main() -> None:
    root = Path.cwd()
    for dirpath, _dirnames, _filenames in os.walk(root):
        current = Path(dirpath)
        if is_git_repo(current):
            git_pull(current)
    print("\nDone.")


if __name__ == "__main__":
    raise SystemExit(main())
