#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_git_command(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git"] + args, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"❌ Git error executing {' '.join(e.cmd)}:\n{e.stderr.strip()}")
        sys.exit(1)


def main():
    repo_root = Path(".")
    if (
        not (repo_root / ".git").exists()
        and not run_git_command(["rev-parse", "--is-inside-work-tree"]) == "true"
    ):
        print("❌ Error: Current directory is not a Git repository root.")
        sys.exit(1)
    try:
        run_git_command(["log", "-1"])
    except SystemExit:
        print(
            "❌ Error: No previous commit found to squash into. Create an initial commit first."
        )
        sys.exit(1)
    print("🔍 Searching repository history for deleted files...")
    log_output = run_git_command(
        ["log", "--diff-filter=D", "--name-only", "--pretty=format:"]
    )
    historically_deleted = {
        line.strip() for line in log_output.splitlines() if line.strip()
    }
    if not historically_deleted:
        print("ℹ️  No deleted files found in the git commit log.")
        return
    status_output = run_git_command(["status", "--porcelain"])
    locally_removed_files = []
    for line in status_output.splitlines():
        if len(line) > 3:
            status = line[:2]
            path = line[3:].strip()
            if "D" in status and path in historically_deleted:
                locally_removed_files.append(path)
    if not locally_removed_files:
        print("🎉 No pending file deletions match historical records.")
        return
    print(
        f"⚠️  Found {len(locally_removed_files)} deleted file(s) to squash into the last commit:"
    )
    for path in locally_removed_files:
        print(f"   -> {path}")
    print("\n🛠️  Staging file deletions...")
    for path in locally_removed_files:
        run_git_command(["add", path])
    print("💾 Squashing changes into previous commit (git commit --amend --no-edit)...")
    amend_output = run_git_command(["commit", "--amend", "--no-edit"])
    print("\n📊 Git Amend Summary:")
    print(amend_output)


if __name__ == "__main__":
    raise SystemExit(main())
