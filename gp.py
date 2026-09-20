#!/data/data/com.termux/files/home/.local/bin/python
"""Auto-commit and push the current git repository using dulwich.

Pipeline:
    1. Copy ``~/.gitignore`` to a local ``.gitignore`` if one is missing.
    2. (optional) Run ``ruff format`` on every ``.py`` file in the repo.
    3. (optional) Parse every ``.py`` file with ``ast.parse`` to catch
       syntax errors.
    4. Stage everything, commit with a timestamped message, and push the
       current branch to ``origin``.

Formatting and syntax validation are **off by default**. Opt in with
``--format`` and/or ``--validate``. This keeps the default behavior
side-effect-free: no file rewriting, no hard failure on unrelated
broken files.
"""

from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dulwich import porcelain
from dulwich.errors import GitProtocolError, NotGitRepository
from dulwich.repo import Repo


# Directories we never want to walk into when collecting .py files. These
# are almost always third-party or generated code that shouldn't be
# reformatted or validated by this script.
SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "build",
    "dist",
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    ``argv`` is optional so this function (and ``main``) can be unit-tested
    without monkeypatching ``sys.argv``. Passing ``None`` falls back to
    ``sys.argv[1:]``, which is what we want when run as a script.
    """
    parser = argparse.ArgumentParser(
        description="Auto-commit and push the current git repository.",
        # Both optional steps default to off — see module docstring.
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--format",
        dest="format",
        action="store_true",
        default=False,
        help="Run `ruff format` on all .py files before committing.",
    )
    parser.add_argument(
        "--validate",
        dest="validate",
        action="store_true",
        default=False,
        help="Parse all .py files with `ast.parse` before committing.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Repository helpers
# ---------------------------------------------------------------------------


def copy_global_gitignore() -> None:
    """Copy ``~/.gitignore`` to a local ``.gitignore`` if one doesn't exist.

    Best-effort: silently does nothing if the local file already exists or
    if the home-level file can't be read/written. Never aborts the commit.
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
    virtualenv / build directories. Results are absolute, de-duplicated,
    and sorted for deterministic iteration order.
    """
    root = Path(repo.path)
    seen: set[Path] = set()
    py_files: list[Path] = []

    def _add(path: Path) -> None:
        # Resolve so a tracked file and an untracked file pointing at the
        # same inode don't get added twice.
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

    # 1. Index-tracked files. We read the raw index rather than shelling
    #    out to `git ls-files` so we don't depend on the git CLI.
    try:
        for entry in repo.open_index().items():
            _add(root / entry.path.decode("utf-8", "surrogateescape"))
    except Exception as e:
        print(f"Warning: could not read index: {e}", file=sys.stderr)

    # 2. Untracked files on disk. rglob skips nothing, so filter manually.
    for path in root.rglob("*.py"):
        parts = path.relative_to(root).parts
        if any(p in SKIP_DIR_NAMES or p.endswith(".egg-info") for p in parts):
            continue
        _add(path)

    py_files.sort()
    return py_files


# ---------------------------------------------------------------------------
# Optional pipeline steps
# ---------------------------------------------------------------------------


def run_ruff_format(files: list[Path]) -> None:
    """Run ``ruff format`` on the given files.

    Exits the process on failure so we never commit or push unformatted
    code. A missing ``ruff`` binary is only a warning (we don't want to
    hard-fail just because the user hasn't installed it).
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


def validate_python_syntax(files: list[Path]) -> None:
    """Parse every ``.py`` file with ``ast.parse``, exiting on syntax errors.

    Unlike ``py_compile``, ``ast.parse`` has no side effects: it does not
    write ``.pyc`` files into ``__pycache__/``. That's the right behavior
    for a pre-commit hook, where we only want to *check* the code, not
    produce build artifacts.
    """
    if not files:
        print("Syntax validation: no .py files found.")
        return

    failures: list[tuple[Path, BaseException]] = []
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
            # Pass filename= explicitly so SyntaxError messages reference
            # the real path instead of "<unknown>".
            ast.parse(source, filename=str(path))
        except SyntaxError as e:
            failures.append((path, e))
        except Exception as e:
            # E.g. UnicodeDecodeError, PermissionError, FileNotFoundError.
            failures.append((path, e))

    if not failures:
        print(f"Syntax validation: OK ({len(files)} file(s) parsed).")
        return

    print(
        f"Syntax validation: FAILED ({len(failures)} of {len(files)} file(s)).",
        file=sys.stderr,
    )
    for path, err in failures:
        if isinstance(err, SyntaxError):
            # Match the familiar CPython format: file:line:col: message.
            print(
                f"  {path}:{err.lineno}:{err.offset}: {err.msg}",
                file=sys.stderr,
            )
        else:
            print(f"  {path}: {err}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    repo = open_repo()
    copy_global_gitignore()

    try:
        # Only walk the work tree if at least one optional step needs it.
        # This avoids a pointless rglob over the whole repo when both
        # --format and --validate are off (the default).
        py_files: list[Path] = []
        if args.format or args.validate:
            py_files = find_python_files(repo)

        # 1. Optionally format. Note: this rewrites files on disk, which
        #    is why it must run *before* we stage anything below.
        if args.format:
            run_ruff_format(py_files)
        else:
            print("Skipping ruff format (--format not given).")

        # 2. Optionally validate that the (possibly rewritten) sources
        #    still parse. Runs after formatting so we check what we're
        #    about to commit, not what was there before.
        if args.validate:
            validate_python_syntax(py_files)
        else:
            print("Skipping syntax validation (--validate not given).")

        # 3. Stage everything in the work tree.
        porcelain.add(repo, [b"."])

        # 4. Commit with a timestamped message.
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_msg = f"Auto-commit at {now}"
        porcelain.commit(repo, commit_msg.encode("utf-8"))

        # 5. Push the current branch to origin.
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
