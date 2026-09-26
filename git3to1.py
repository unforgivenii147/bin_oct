#!/data/data/com.termux/files/home/.local/bin/python
"""Squash the last N commits into one and set the commit date to today.

Usage:
    python squash_commits.py [--count 3] [--date "2026-09-27 14:30:00"]
    python squash_commits.py -c 3 -d "today"

Requires:
    - git installed and available in PATH
    - You must be inside a git repository
    - The last N commits must not have been pushed yet (or you accept
      force-pushing to overwrite remote history)
"""

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command and return the result.

    Args:
        args: Git command arguments (without the leading "git").
        check: If True, raise CalledProcessError on non-zero exit.

    Returns:
        CompletedProcess instance.

    Raises:
        subprocess.CalledProcessError: If check=True and git exits non-zero.
    """
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=check,
    )
    return result


def get_commit_count() -> int:
    """Return the total number of commits in the current branch."""
    result = run_git(["rev-list", "--count", "HEAD"])
    return int(result.stdout.strip())


def get_commit_message(commit: str) -> str:
    """Get the full commit message of a given commit."""
    result = run_git(["log", "-1", "--format=%B", commit])
    return result.stdout


def squash_commits(count: int, commit_date: str | None = None) -> bool:
    """Squash the last `count` commits into one.

    Args:
        count: Number of commits to squash (must be >= 2).
        commit_date: Optional date string for the squashed commit.
            If None, uses the current date/time.

    Returns:
        True on success, False on failure.
    """
    if count < 2:
        print(f"Error: Need at least 2 commits to squash, got {count}", file=sys.stderr)
        return False

    # Verify we're in a git repo
    try:
        run_git(["rev-parse", "--git-dir"])
    except subprocess.CalledProcessError:
        print("Error: Not inside a git repository", file=sys.stderr)
        return False

    # Check we have enough commits
    total_commits = get_commit_count()
    if count > total_commits:
        print(
            f"Error: Only {total_commits} commit(s) available, cannot squash {count}",
            file=sys.stderr,
        )
        return False

    # Get the commit messages for the commits we're squashing
    # (we'll use the first commit's message as the squashed message)
    first_commit = run_git(["rev-parse", f"HEAD~{count - 1}"]).stdout.strip()
    commit_message = get_commit_message(first_commit)

    # Build the rebase todo list
    # Format: "pick <sha> <subject>" for the first, "squash <sha> <subject>" for the rest
    todo_lines = []
    for i in range(count):
        commit_sha = run_git(["rev-parse", f"HEAD~{count - 1 - i}"]).stdout.strip()
        subject = run_git(["log", "-1", "--format=%s", commit_sha]).stdout.strip()
        action = "pick" if i == 0 else "squash"
        todo_lines.append(f"{action} {commit_sha} {subject}")

    todo_text = "\n".join(todo_lines) + "\n"

    # Use GIT_SEQUENCE_EDITOR to provide the todo list non-interactively
    # We write the todo to a temp file and use a script that copies it
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        editor_script = f"""
#!/bin/sh
cat > "\$1" << 'EOF'
{todo_text}
EOF
"""
        f.write(editor_script)
        editor_path = f.name

    try:
        # Make the editor script executable
        Path(editor_path).chmod(0o755)

        # Run the rebase with our custom sequence editor
        env = {"GIT_SEQUENCE_EDITOR": editor_path}
        result = subprocess.run(
            ["git", "rebase", "-i", f"HEAD~{count}"],
            capture_output=True,
            text=True,
            env={**__import__("os").environ, **env},
        )

        if result.returncode != 0:
            print(f"Rebase failed: {result.stderr}", file=sys.stderr)
            # Try to abort the rebase
            run_git(["rebase", "--abort"], check=False)
            return False

    finally:
        # Clean up the temp editor script
        Path(editor_path).unlink(missing_ok=True)

    # Now amend the squashed commit with the desired date
    if commit_date is None:
        # Use current date in RFC 2822 format (what git expects)
        date_str = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    else:
        # Parse the provided date and format it for git
        try:
            # Try common formats
            parsed = datetime.fromisoformat(commit_date.replace("Z", "+00:00"))
            date_str = parsed.strftime("%a, %d %b %Y %H:%M:%S %z")
        except ValueError:
            # Fall back to using the string as-is (git will try to parse it)
            date_str = commit_date

    amend_result = run_git(
        ["commit", "--amend", "--no-edit", "--date", date_str],
        check=False,
    )
    if amend_result.returncode != 0:
        print(f"Failed to amend commit date: {amend_result.stderr}", file=sys.stderr)
        return False

    print(f"Successfully squashed {count} commits into one.")
    print(f"Commit date set to: {date_str}")
    print("\nTo push to remote, run:")
    print("  git push --force-with-lease")
    return True


def main() -> int:
    """Parse arguments and run the squash operation."""
    parser = argparse.ArgumentParser(
        description="Squash the last N commits into one and set the date.",
    )
    parser.add_argument(
        "-c",
        "--count",
        type=int,
        default=3,
        help="Number of commits to squash (default: 3)",
    )
    parser.add_argument(
        "-d",
        "--date",
        default=None,
        help=(
            'Commit date. Use "today" for current date, or an ISO format '
            'string like "2026-09-27 14:30:00". Default: current date/time.'
        ),
    )
    args = parser.parse_args()

    # Handle "today" keyword
    if args.date and args.date.lower() == "today":
        args.date = None  # None means "use current date"

    success = squash_commits(args.count, args.date)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
