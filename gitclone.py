#!/data/data/com.termux/files/home/.local/bin/python
"""
Clone a repo as a bare, single-branch mirror of its default branch,
including all submodules (recursively).
Usage: g2 <repo-url> [target-dir]
"""

import re
import subprocess
import sys
from pathlib import Path


def _default_branch(url: str) -> str | None:
    """Ask the remote what HEAD points to, e.g. 'main' or 'master'."""
    result = subprocess.run(
        ["git", "ls-remote", "--symref", url, "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        m = re.match(r"^ref:\s+refs/heads/(\S+)\s+HEAD", line)
        if m:
            return m.group(1)
    return None


def _has_submodules(repo_dir: Path) -> bool:
    """True if the bare repo has a .gitmodules file in its tree."""
    rc = subprocess.run(
        ["git", "-C", str(repo_dir), "cat-file", "-e", "HEAD:.gitmodules"],
        capture_output=True,
    ).returncode
    return rc == 0


def git_clone2(*args):
    if not args:
        print("Usage: g2 <repo-url> [target-dir]")
        return 1

    url = args[0]
    target = args[1] if len(args) > 1 else ""

    branch = _default_branch(url)
    if not branch:
        print(f"❌ Could not determine default branch for {url}", file=sys.stderr)
        return 1

    repo = Path(url.rstrip("/")).name
    if repo.endswith(".git"):
        repo = repo[:-4]

    if not target:
        target = f"{repo}.git"

    print(f"🔍 Default branch: {branch}")
    print(f"📦 Cloning only '{branch}' (with submodules) from {url} into {target} ...")

    # --recurse-submodules on a bare clone creates bare submodule repos
    # in the same relative paths. Requires git >= 2.13.
    rc = subprocess.run(
        [
            "git",
            "clone",
            "--single-branch",
            "--branch",
            branch,
            "--bare",
            "--recurse-submodules",
            url,
            target,
        ]
    ).returncode
    if rc != 0:
        return rc

    target_path = Path(target)
    has_subs = _has_submodules(target_path)

    print("✅ Done!")
    print(f"   To update later: cd {target} && git fetch origin {branch}")
    if has_subs:
        print(f"   Update submodules: git submodule update --init --recursive --remote")

    return 0


if __name__ == "__main__":
    sys.exit(git_clone2(*sys.argv[1:]))
