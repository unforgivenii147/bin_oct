#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def get_git_commit(repo_path):
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return commit, branch
    except subprocess.CalledProcessError:
        return None, None


def generate_lazy_lock():
    lazy_dir = Path.home() / ".local" / "share" / "nvim" / "lazy"
    lock_file = Path.home() / ".config" / "nvim" / "lazy-lock.json"
    if not lazy_dir.exists():
        print(f"Error: Lazy directory not found at {lazy_dir}")
        return False
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    plugins_lock = {}
    for plugin_dir in sorted(lazy_dir.iterdir()):
        if not plugin_dir.is_dir():
            continue
        plugin_name = plugin_dir.name
        git_dir = plugin_dir / ".git"
        if not git_dir.exists():
            print(f"Skipping {plugin_name}: Not a git repository")
            continue
        commit, branch = get_git_commit(plugin_dir)
        if commit and branch:
            plugins_lock[plugin_name] = {"branch": branch, "commit": commit}
            print(f"✓ {plugin_name}: {commit[:8]} ({branch})")
        else:
            print(f"✗ {plugin_name}: Failed to get git information")
    try:
        with open(lock_file, "w") as f:
            json.dump(plugins_lock, f, indent=2)
            f.write("\n")
        print(f"\n✓ Successfully wrote lock file to {lock_file}")
        print(f"  Total plugins: {len(plugins_lock)}")
        return True
    except OSError as e:
        print(f"Error writing lock file: {e}")
        return False


def main():
    print("Generating lazy-lock.json for Neovim plugins...")
    print(f"Scanning: {Path.home() / '.local' / 'share' / 'nvim' / 'lazy'}")
    print(f"Output: {Path.home() / '.config' / 'nvim' / 'lazy-lock.json'}")
    print("-" * 40)
    success = generate_lazy_lock()
    if success:
        print("\nDone! You can now use this lock file with lazy.nvim.")
    else:
        print("\nFailed to generate lock file.")
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
