#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TARGET_PREFIX = "2026-08-29"


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Git command failed")
    return result.stdout.strip()


def is_git_repo(path: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=path,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def process_repo(repo: Path) -> None:
    repo_name = repo.name
    try:
        latest_message = run_git(repo, "log", "-1", "--format=%s")
        if not latest_message.startswith(TARGET_PREFIX):
            print(
                f"[skip] {repo_name}: latest commit does not start with {TARGET_PREFIX}"
            )
            return
        current_commit = run_git(repo, "rev-parse", "--short", "HEAD")
        parent_commit = run_git(repo, "rev-parse", "HEAD^")
        short_parent = run_git(repo, "rev-parse", "--short", parent_commit)
        print(f"\n[match] Repository: {repo_name}")
        print(f"        Path: {repo}")
        print(f"        Current commit: {current_commit}")
        print(f"        Latest message: {latest_message}")
        print(f"        Target commit: {short_parent}")
        answer = (
            input(f"Checkout {short_parent} in {repo_name}? [y/N]: ").strip().lower()
        )
        if answer not in {"y", "yes"}:
            print(f"[skip] {repo_name}: checkout cancelled")
            return
        run_git(repo, "checkout", parent_commit)
        print(f"[done] {repo_name}: now at {short_parent}")
    except RuntimeError as error:
        print(f"[error] {repo_name}: {error}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(130)


def main() -> None:
    current_dir = Path.cwd()
    candidates = [current_dir]
    candidates.extend(
        path
        for path in current_dir.iterdir()
        if path.is_dir() and not path.is_symlink()
    )
    repos = [path for path in candidates if is_git_repo(path)]
    if not repos:
        print("No Git repositories found.")
        return
    for repo in repos:
        process_repo(repo)


if __name__ == "__main__":
    main()
