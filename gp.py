#!/data/data/com.termux/files/home/.local/bin/python
"""Auto-commit and push the current git repository using dulwich.

Pipeline:
    1. Copy ``~/.gitignore`` to a local ``.gitignore`` if missing.
    2. Run ``ruff format`` on every ``.py`` file in the repo.
    3. Compile every ``.py`` file to catch syntax errors.
    4. Stage everything, commit with a timestamped message, and push
       the current branch to ``origin``.
"""

from __future__ import annotations

import py_compile
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dulwich import porcelain
from dulwich.errors import GitProtocolError, NotGitRepository
from dulwich.repo import Repo


# Directories/files we never want to touch with ruff or the syntax check.
SKIP_DIR_NAMES = {".git", ".venv", "venv", "env", "__pycache__", "build", "dist"}


def copy_global_gitignore() -> None:
    """Copy ``~/.gitignore`` to a local ``.gitignore`` if one doesn't exist.

    Silently does nothing when the local file already exists or when the
    home-level file cannot be read/written.
    """
    home_gitignore = Path.home() / ".gitignore"
    local_gitignore = Path(".gitignore")
    if local_gitignore.exists():
        return
    try:
        data = home_gitignore.read_text(encoding="utf-8")
        local_gitignore.write_text(data, encoding="utf-8")
    except Exception:
        # Best-effort — never fail the commit because of this.
        return


def open_repo() -> Repo:
    """Locate and open the git repository containing the current directory."""
    try:
        return Repo.discover(".")
    except NotGitRepository:
        print("Error: Not a git repository.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error accessing repository: {e}", file=sys.stderr)
        sys.exit(1)


def active_branch_name(repo: Repo) -> str:
    """Return the name of the checked-out branch, or exit on detached HEAD."""
    try:
        return porcelain.active_branch(repo)
    except (ValueError, KeyError):
        print(
            "Error: Could not detect current branch (detached HEAD?).",
            file=sys.stderr,
        )
        sys.exit(1)


def find_python_files(repo: Repo) -> list[Path]:
    """Return every ``.py`` file inside the repository's work tree.

    Includes both index-tracked files and untracked working-tree files so
    freshly-created files are covered too. Skips ``.git/`` and common
    virtualenv / build directories.
    """
    root = Path(repo.path)
    seen: set[Path] = set()
    py_files: list[Path] = []

    def _add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        if resolved in seen or not resolved.is_file():
            return
        if resolved.suffix != ".py":
            return
        seen.add(resolved)
        py_files.append(resolved)

    # Tracked files (index).
    try:
        for entry in repo.open_index().items():
            _add(root / entry.path.decode("utf-8", "surrogateescape"))
    except Exception as e:
        print(f"Warning: could not read index: {e}", file=sys.stderr)

    # Untracked working-tree files.
    for path in root.rglob("*.py"):
        parts = path.relative_to(root).parts
        if any(p in SKIP_DIR_NAMES or p.endswith(".egg-info") for p in parts):
            continue
        _add(path)

    return py_files


def run_ruff_format(files: list[Path]) -> None:
    """Run ``ruff format`` on the given files.

    Exits the process on failure so we never commit or push unformatted
    code. Missing ``ruff`` is only a warning.
    """
    ruff = shutil.which("ruff")
    if ruff is None:
        print(
            "Warning: ruff not found on PATH; skipping formatting.",
            file=sys.stderr,
        )
        return

    if not files:
        print("ruff format: no .py files to format.")
        return

    result = subprocess.run(
        [ruff, "format", *[str(f) for f in files]],
        capture_output=True,
        text=True,
    )

    # Echo whatever ruff printed (it lists reformatted files).
    if result.stdout.strip():
        print(result.stdout.strip())

    if result.returncode != 0:
        print("ruff format failed:", file=sys.stderr)
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        sys.exit(result.returncode)


def check_python_syntax(files: list[Path]) -> None:
    """Compile every ``.py`` file, exiting if any has a syntax error.

    Uses ``py_compile`` so nothing is executed — this is a parse-only pass.
    """
    if not files:
        print("Syntax check: no .py files found.")
        return

    failures: list[tuple[Path, object]] = []
    for path in files:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as e:
            failures.append((path, getattr(e, "exc_value", e)))
        except Exception as e:
            failures.append((path, e))

    if not failures:
        print(f"Syntax check: OK ({len(files)} file(s) compiled).")
        return

    print(
        f"Syntax check: FAILED ({len(failures)} of {len(files)} file(s)).",
        file=sys.stderr,
    )
    for path, err in failures:
        if isinstance(err, SyntaxError):
            print(
                f"  {path}:{err.lineno}:{err.offset}: {err.msg}",
                file=sys.stderr,
            )
        else:
            print(f"  {path}: {err}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    repo = open_repo()
    copy_global_gitignore()

    try:
        py_files = find_python_files(repo)

        # 1. Format, then 2. verify it still parses.
        run_ruff_format(py_files)
        check_python_syntax(py_files)

        # 3. Stage everything (including any files ruff just rewrote).
        porcelain.add(repo, [b"."])

        # 4. Commit.
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_msg = f"Auto-commit at {now}"
        porcelain.commit(repo, commit_msg.encode("utf-8"))

        # 5. Push.
        branch = active_branch_name(repo)
        porcelain.push(
            repo,
            "origin",
            f"refs/heads/{branch}:refs/heads/{branch}",
        )
        print(f"Pushed to origin/{branch} with message: {commit_msg}")
    except GitProtocolError as e:
        print(f"Git command error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
