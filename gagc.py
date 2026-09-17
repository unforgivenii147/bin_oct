#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
from datetime import datetime

from git import Repo


def git_commit_all() -> None:
    try:
        repo = Repo(os.getcwd())
    except:
        repo = Repo.init(os.getcwd())
    repo.index.add("*")
    if repo.index.diff("HEAD"):
        commit_message = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        repo.index.commit(commit_message)
        print(f"Committed: {commit_message}")
    else:
        print("No changes to commit")


if __name__ == "__main__":
    git_commit_all()
