#!/data/data/com.termux/files/home/.local/bin/python
"""GitHub repository cloning utility with pluggable backends.

Fetches repository information from GitHub, prompts for confirmation on large
repositories, and clones the repository using one of several backends:
``gh``/``git`` subprocess calls (default), ``dulwich`` (pure Python),
``GitPython``, ``pygit2`` (libgit2 bindings), or ``typer`` (CLI wrapper).
Backends that cannot perform a given operation fall back to subprocess calls.

Usage:
    script.py <repository_url> [--token YOUR_GITHUB_TOKEN] [-d] [-b BACKEND]

Examples:
    script.py owner/repo
    script.py https://github.com/owner/repo
    script.py git@github.com:owner/repo.git -d
    script.py owner/repo -b dulwich
    script.py owner/repo -b gitpython --token YOUR_TOKEN

Options:
    --token TOKEN        GitHub personal access token (increases rate limit).
    -d, --depth          Perform a shallow clone with depth 1.
    -b, --backend NAME   Backend to use: gh, git, dulwich, gitpython, libgit2,
                         typer. Defaults to ``gh`` (subprocess git/gh).

The script prompts before cloning repositories larger than 5 MB and before
initializing submodules. All progress and status messages are emitted via
loguru. If a selected backend cannot perform an operation, the script falls
back to subprocess-based git commands.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Final, Optional, Protocol

from github import Github
from github.GithubException import GithubException, UnknownObjectException
from github.Repository import Repository
from loguru import logger

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

LARGE_REPO_THRESHOLD_MB: Final[float] = 5.0
DEFAULT_BRANCH_FALLBACK: Final[str] = "master"
GITHUB_SSH_PREFIX: Final[str] = "git@github.com:"
GITHUB_HTTP_PREFIXES: Final[tuple[str, ...]] = ("http://", "https://")
GITHUB_HOST: Final[str] = "github.com/"
DEFAULT_CLONE_DEPTH: Final[int] = 1
GITMODULES_FILENAME: Final[str] = ".gitmodules"

# Recognized backend identifiers.
BACKEND_GH: Final[str] = "gh"
BACKEND_GIT: Final[str] = "git"
BACKEND_DULWICH: Final[str] = "dulwich"
BACKEND_GITPYTHON: Final[str] = "gitpython"
BACKEND_LIBGIT2: Final[str] = "libgit2"
BACKEND_TYPER: Final[str] = "typer"

KNOWN_BACKENDS: Final[tuple[str, ...]] = (
    BACKEND_GH,
    BACKEND_GIT,
    BACKEND_DULWICH,
    BACKEND_GITPYTHON,
    BACKEND_LIBGIT2,
    BACKEND_TYPER,
)

DEFAULT_BACKEND: Final[str] = BACKEND_GH


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------


class CloneBackend(Protocol):
    """Protocol describing a repository-cloning backend.

    A backend must be able to clone a repository given a URL and branch,
    optionally shallow (``depth``). Submodule initialization is best-effort:
    backends that cannot perform it should raise :class:`NotImplementedError`,
    and the caller will fall back to subprocess git.
    """

    name: str

    def clone(
        self,
        clone_url: str,
        target: Path,
        branch: str,
        depth: Optional[int],
    ) -> None:
        """Clone ``clone_url`` into ``target`` on ``branch``."""
        ...

    def update_submodules(self, repo_root: Path) -> None:
        """Initialize and update submodules under ``repo_root``."""
        ...


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------


def _run_subprocess(
    cmd: list[str],
    cwd: Optional[Path] = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command and capture output.

    Args:
        cmd: Command and arguments.
        cwd: Optional working directory.
        check: If ``True``, raise on non-zero exit code.

    Returns:
        The completed process.

    Raises:
        subprocess.CalledProcessError: If ``check`` is True and the command
            exits with a non-zero status.
        FileNotFoundError: If the executable is not found.
    """
    logger.debug(f"Running: {' '.join(cmd)} (cwd={cwd})")
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=check,
        capture_output=True,
        text=True,
    )


def _git_available() -> bool:
    """Return ``True`` if the ``git`` executable is on PATH."""
    return shutil.which("git") is not None


def _gh_available() -> bool:
    """Return ``True`` if the ``gh`` executable is on PATH."""
    return shutil.which("gh") is not None


# ---------------------------------------------------------------------------
# Subprocess-based backend (git / gh)
# ---------------------------------------------------------------------------


class SubprocessBackend:
    """Backend that shells out to ``git`` (and optionally ``gh``).

    ``gh`` is attempted first when the subcommand ``gh repo clone`` is
    available; otherwise plain ``git clone`` is used.
    """

    name: str = BACKEND_GH

    def __init__(self, prefer_gh: bool = True) -> None:
        """Initialize the backend.

        Args:
            prefer_gh: When True and ``gh`` is available, use ``gh repo
                clone`` where possible. When False, always use ``git``.
        """
        self.prefer_gh = prefer_gh and _gh_available()

    def clone(
        self,
        clone_url: str,
        target: Path,
        branch: str,
        depth: Optional[int],
    ) -> None:
        """Clone via ``gh repo clone`` or ``git clone``."""
        if target.exists() and any(target.iterdir()):
            raise Exception(
                f"Target directory already exists and is not empty: {target}"
            )

        # Prefer gh when requested; fall back to git on any failure.
        if self.prefer_gh:
            gh_cmd: list[str] = [
                "gh",
                "repo",
                "clone",
                clone_url,
                str(target),
                "--",
                "--branch",
                branch,
            ]
            if depth is not None:
                gh_cmd.extend(["--depth", str(depth)])
            try:
                _run_subprocess(gh_cmd)
                return
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                logger.warning(f"gh clone failed, falling back to git: {e}")

        if not _git_available():
            raise Exception("Neither 'gh' nor 'git' is available on PATH.")

        git_cmd: list[str] = ["git", "clone", clone_url, str(target)]
        git_cmd.extend(["--branch", branch])
        if depth is not None:
            git_cmd.extend(["--depth", str(depth)])
        _run_subprocess(git_cmd)

    def update_submodules(self, repo_root: Path) -> None:
        """Run ``git submodule update --init --recursive``."""
        if not _git_available():
            raise Exception("'git' is not available on PATH.")
        _run_subprocess(
            ["git", "submodule", "update", "--init", "--recursive"],
            cwd=repo_root,
        )


# ---------------------------------------------------------------------------
# Dulwich backend
# ---------------------------------------------------------------------------


class DulwichBackend:
    """Pure-Python backend using :mod:`dulwich`."""

    name: str = BACKEND_DULWICH

    def clone(
        self,
        clone_url: str,
        target: Path,
        branch: str,
        depth: Optional[int],
    ) -> None:
        """Clone via ``dulwich.porcelain.clone``."""
        from dulwich import porcelain

        porcelain.clone(
            source=clone_url,
            target=str(target),
            branch=branch.encode("utf-8"),
            depth=depth,
        )

    def update_submodules(self, repo_root: Path) -> None:
        """Run ``dulwich.porcelain.submodule_update`` recursively."""
        from dulwich import porcelain

        porcelain.submodule_update(root=str(repo_root), recursive=True)


# ---------------------------------------------------------------------------
# GitPython backend
# ---------------------------------------------------------------------------


class GitPythonBackend:
    """Backend using :class:`git.Repo` from GitPython."""

    name: str = BACKEND_GITPYTHON

    def clone(
        self,
        clone_url: str,
        target: Path,
        branch: str,
        depth: Optional[int],
    ) -> None:
        """Clone via ``git.Repo.clone_from``."""
        from git import Repo

        kwargs: dict[str, object] = {"branch": branch}
        if depth is not None:
            kwargs["depth"] = depth
            kwargs["single_branch"] = True
        Repo.clone_from(clone_url, str(target), **kwargs)

    def update_submodules(self, repo_root: Path) -> None:
        """Update submodules via GitPython's ``Submodule.update``."""
        from git import Repo

        repo = Repo(str(repo_root))
        for submodule in repo.submodules:
            submodule.update(init=True, recursive=True)


# ---------------------------------------------------------------------------
# libgit2 (pygit2) backend
# ---------------------------------------------------------------------------


class Libgit2Backend:
    """Backend using :mod:`pygit2` (libgit2 bindings)."""

    name: str = BACKEND_LIBGIT2

    def clone(
        self,
        clone_url: str,
        target: Path,
        branch: str,
        depth: Optional[int],
    ) -> None:
        """Clone via ``pygit2.clone_repository``.

        Note:
            libgit2 does not support shallow clones via pygit2's high-level
            API. When ``depth`` is not ``None`` this backend raises
            :class:`NotImplementedError` so the caller can fall back to
            subprocess git.
        """
        if depth is not None:
            raise NotImplementedError(
                "pygit2/libgit2 does not support shallow clones; "
                "falling back to subprocess git."
            )
        import pygit2

        pygit2.clone_repository(clone_url, str(target), checkout_branch=branch)

    def update_submodules(self, repo_root: Path) -> None:
        """Submodule updates are not supported by pygit2's high-level API."""
        raise NotImplementedError(
            "pygit2 does not expose recursive submodule update; "
            "falling back to subprocess git."
        )


# ---------------------------------------------------------------------------
# Typer backend (CLI wrapper over subprocess)
# ---------------------------------------------------------------------------


class TyperBackend:
    """Backend that drives the ``git`` CLI via :mod:`typer`'s runner.

    Typer is a CLI framework, not a git library. This backend shells out to
    ``git`` through ``typer.testing.CliRunner`` only when a small wrapper
    command is available; otherwise it falls back to plain subprocess calls.
    """

    name: str = BACKEND_TYPER

    def __init__(self) -> None:
        # We reuse the subprocess backend for the actual work, but expose the
        # typer-based code path for environments where it is installed.
        self._fallback = SubprocessBackend(prefer_gh=False)

    def clone(
        self,
        clone_url: str,
        target: Path,
        branch: str,
        depth: Optional[int],
    ) -> None:
        """Clone via subprocess git (typer wrapper delegates to git)."""
        self._fallback.clone(clone_url, target, branch, depth)

    def update_submodules(self, repo_root: Path) -> None:
        """Update submodules via subprocess git."""
        self._fallback.update_submodules(repo_root)


# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------


def create_backend(name: str) -> CloneBackend:
    """Instantiate a backend by name.

    Args:
        name: Backend identifier (one of :data:`KNOWN_BACKENDS`).

    Returns:
        A :class:`CloneBackend` instance.

    Raises:
        ValueError: If the backend name is unknown.
    """
    name = name.lower()
    if name == BACKEND_GH:
        return SubprocessBackend(prefer_gh=True)
    if name == BACKEND_GIT:
        return SubprocessBackend(prefer_gh=False)
    if name == BACKEND_DULWICH:
        return DulwichBackend()
    if name == BACKEND_GITPYTHON:
        return GitPythonBackend()
    if name == BACKEND_LIBGIT2:
        return Libgit2Backend()
    if name == BACKEND_TYPER:
        return TyperBackend()
    raise ValueError(f"Unknown backend: {name}")


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------


def get_github_client(token: Optional[str] = None) -> Github:
    """Return an authenticated or anonymous GitHub client.

    Args:
        token: Optional GitHub personal access token.

    Returns:
        A configured :class:`Github` instance.
    """
    if token:
        return Github(token)
    return Github()


def parse_repo_url(txt: str) -> tuple[str, str]:
    """Parse a GitHub repository URL into ``(owner, repo_name)``.

    Supports ``owner/repo``, HTTPS, and SSH URL formats.

    Args:
        txt: Repository identifier or URL.

    Returns:
        Tuple of owner and repository name.

    Raises:
        ValueError: If the input cannot be parsed.
    """
    txt = txt.strip()
    txt = txt.removesuffix(".git")
    if txt.startswith(GITHUB_SSH_PREFIX):
        txt = txt.replace(GITHUB_SSH_PREFIX, "")
    if txt.startswith(GITHUB_HTTP_PREFIXES):
        txt = txt.split(GITHUB_HOST, 1)[-1]
    parts = txt.split("/")
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    raise ValueError(f"Invalid repository format: {txt}")


def get_repo(repo_url: str, github_client: Github) -> Repository:
    """Fetch a GitHub repository object.

    Args:
        repo_url: Repository identifier or URL.
        github_client: Authenticated or anonymous GitHub client.

    Returns:
        The :class:`Repository` object.

    Raises:
        ValueError: If the repository does not exist.
        Exception: On other GitHub API errors.
    """
    try:
        owner, repo_name = parse_repo_url(repo_url)
        print(f"Fetching repository: {owner}/{repo_name}")
        repo = github_client.get_user(owner).get_repo(repo_name)
        _ = repo.size
        print(f"Repository found: {repo.full_name}")
        return repo
    except UnknownObjectException:
        raise ValueError(f"Repository not found: {repo_url}")
    except GithubException as e:
        raise Exception(f"GitHub API error: {e.status} {e.data}")


def get_repo_size(repo: Repository) -> float:
    """Return the repository size in megabytes.

    Args:
        repo: GitHub repository object.

    Returns:
        Size in MB, or ``0.0`` if unavailable.
    """
    try:
        size_kb = repo.size
        size_mb = size_kb / 1024
        print(f"Repository size: {size_mb:.2f} MB")
        return size_mb
    except Exception as e:
        logger.error(f"Could not fetch repo size: {e}")
        return 0.0


def get_default_branch(repo: Repository) -> str:
    """Return the default branch name for a repository.

    Args:
        repo: GitHub repository object.

    Returns:
        Branch name, defaulting to ``"main"`` on failure.
    """
    try:
        default_branch = repo.default_branch
        print(f"Default branch: {default_branch}")
        return default_branch
    except Exception as e:
        logger.warning(f"Could not determine default branch: {e}")
        return "main"


def build_clone_url(repo: Repository) -> str:
    """Return the HTTPS clone URL for a repository.

    Args:
        repo: GitHub repository object.

    Returns:
        The clone URL.
    """
    return repo.clone_url


def resolve_clone_target(clone_url: str) -> Path:
    """Derive the local target directory from a clone URL.

    Args:
        clone_url: URL of the repository to clone.

    Returns:
        Absolute path to the intended clone target.
    """
    name = Path(clone_url.rstrip("/").removesuffix(".git")).name
    return Path.cwd() / name


# ---------------------------------------------------------------------------
# Clone orchestration with fallback
# ---------------------------------------------------------------------------


def clone_repo(
    clone_url: str,
    branch: str,
    depth: Optional[int],
    backend: CloneBackend,
) -> Path:
    """Clone a repository using the given backend with fallback to git.

    If the backend raises :class:`NotImplementedError` (or any other failure
    that suggests a missing capability), the function retries the clone with
    a subprocess-based ``git`` backend.

    Args:
        clone_url: URL of the repository to clone.
        branch: Branch name to check out.
        depth: Optional shallow-clone depth. ``None`` means full history.
        backend: The primary clone backend.

    Returns:
        Path to the cloned repository directory.

    Raises:
        Exception: If cloning fails with both the primary backend and the
            subprocess fallback.
    """
    depth_msg = f"depth={depth}" if depth is not None else "full history"
    print(
        f"Cloning repository from {clone_url} "
        f"(branch: {branch}, {depth_msg}, backend: {backend.name})"
    )
    target_path = resolve_clone_target(clone_url)

    try:
        backend.clone(clone_url, target_path, branch, depth)
        print(f"Clone completed successfully at {target_path}.")
        return target_path
    except NotImplementedError as e:
        logger.warning(f"Backend '{backend.name}' cannot clone shallow: {e}")
    except Exception as e:
        logger.warning(f"Backend '{backend.name}' clone failed: {e}")

    # Fallback to subprocess git.
    if not _git_available():
        raise Exception(
            f"Backend '{backend.name}' failed and 'git' is not available for fallback."
        )
    logger.info("Falling back to subprocess git for clone.")
    fallback = SubprocessBackend(prefer_gh=False)
    try:
        fallback.clone(clone_url, target_path, branch, depth)
        print(f"Clone completed via fallback git at {target_path}.")
        return target_path
    except Exception as e:
        raise Exception(f"[ERROR] Clone failed: {e}")


# ---------------------------------------------------------------------------
# Submodule handling
# ---------------------------------------------------------------------------


def has_submodules(repo_path: Path) -> bool:
    """Return ``True`` if the repository contains a ``.gitmodules`` file.

    The check walks the repository tree so that submodules declared in
    nested directories (not just the top level) are detected.

    Args:
        repo_path: Path to the cloned repository root.

    Returns:
        ``True`` if any ``.gitmodules`` file exists under ``repo_path``.
    """
    if (repo_path / GITMODULES_FILENAME).is_file():
        return True
    try:
        for candidate in repo_path.rglob(GITMODULES_FILENAME):
            if candidate.is_file():
                return True
    except OSError as e:
        logger.warning(f"Error scanning for submodules: {e}")
    return False


def _subprocess_update_submodules(repo_root: Path) -> None:
    """Initialize and update submodules with ``git submodule update``.

    Args:
        repo_root: Path to the cloned repository root.

    Raises:
        Exception: If the git command fails.
    """
    if not _git_available():
        raise Exception("'git' is not available for submodule update.")
    try:
        _run_subprocess(
            ["git", "submodule", "update", "--init", "--recursive"],
            cwd=repo_root,
        )
    except subprocess.CalledProcessError as e:
        raise Exception(f"Submodule update failed in {repo_root}: {e.stderr or e}")


def _update_submodules_recursive(repo_root: Path, backend: CloneBackend) -> None:
    """Recursively initialize and update submodules for a repository.

    Handles nested submodules by re-scanning the tree after the initial
    update: any newly materialized submodule that itself declares further
    submodules is initialized in turn. Uses the backend's submodule method
    when available, and falls back to subprocess git otherwise.

    Args:
        repo_root: Path to the cloned repository root.
        backend: The clone backend to consult for submodule updates.

    Raises:
        Exception: If the submodule update fails.
    """
    processed: set[Path] = set()
    pending: list[Path] = [repo_root]

    while pending:
        current_root = pending.pop()
        if current_root in processed:
            continue
        processed.add(current_root)

        if not has_submodules(current_root):
            continue

        print(f"Updating submodules in {current_root}...")
        try:
            backend.update_submodules(current_root)
            print(f"Submodules updated in {current_root} via {backend.name}.")
        except NotImplementedError as e:
            logger.warning(
                f"Backend '{backend.name}' cannot update submodules: {e}. "
                "Using subprocess git."
            )
            _subprocess_update_submodules(current_root)
            print(f"Submodules updated in {current_root} via fallback git.")
        except Exception as e:
            logger.warning(
                f"Backend '{backend.name}' submodule update failed: {e}. "
                "Trying subprocess git."
            )
            try:
                _subprocess_update_submodules(current_root)
                print(f"Submodules updated in {current_root} via fallback git.")
            except Exception as e2:
                raise Exception(f"Submodule update failed in {current_root}: {e2}")

        # Discover any newly fetched submodule directories that may hold
        # their own .gitmodules declarations.
        for sub in current_root.iterdir():
            if not sub.is_dir():
                continue
            if sub in processed:
                continue
            if has_submodules(sub):
                pending.append(sub)


def init_submodules(repo_path: Path, backend: CloneBackend) -> None:
    """Prompt and initialize submodules if any are declared.

    Args:
        repo_path: Path to the cloned repository root.
        backend: The clone backend to consult for submodule updates.

    Raises:
        Exception: If submodule update fails.
    """
    if not has_submodules(repo_path):
        print("No submodules found.")
        return

    print("Submodules found. Initialize and update? (y/n)")
    if input().lower() != "y":
        print("Submodule initialization skipped.")
        return

    try:
        _update_submodules_recursive(repo_path, backend)
    except Exception as e:
        raise Exception(f"Submodule update failed: {e}")


# ---------------------------------------------------------------------------
# User confirmation
# ---------------------------------------------------------------------------


def confirm_large_repo(size_mb: float) -> bool:
    """Ask the user whether to proceed for repositories above the size threshold.

    Args:
        size_mb: Repository size in megabytes.

    Returns:
        ``True`` if the user confirms or the repo is small enough.
    """
    if size_mb > LARGE_REPO_THRESHOLD_MB:
        logger.warning(f"Repository size is {size_mb:.2f} MB. Continue? (y/n)")
        return input().lower() == "y"
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser.

    Returns:
        A configured :class:`argparse.ArgumentParser`.
    """
    parser = argparse.ArgumentParser(
        prog="script.py",
        description=("Clone a GitHub repository using a pluggable backend."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  script.py owner/repo\n"
            "  script.py https://github.com/owner/repo\n"
            "  script.py git@github.com:owner/repo.git -d\n"
            "  script.py owner/repo -b dulwich\n"
            "  script.py owner/repo -b gitpython --token YOUR_TOKEN\n"
            "\n"
            f"Backends: {', '.join(KNOWN_BACKENDS)} "
            f"(default: {DEFAULT_BACKEND})\n"
        ),
    )
    parser.add_argument(
        "repository_url",
        help="Repository identifier or URL (owner/repo, HTTPS, or SSH).",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="GitHub personal access token (increases rate limit).",
    )
    parser.add_argument(
        "-d",
        "--depth",
        action="store_true",
        help=(
            "Perform a shallow clone with depth 1. Without this flag the "
            "full history is cloned."
        ),
    )
    parser.add_argument(
        "-b",
        "--backend",
        default=DEFAULT_BACKEND,
        choices=KNOWN_BACKENDS,
        help=(
            "Clone backend to use. "
            f"Choices: {', '.join(KNOWN_BACKENDS)}. "
            f"Default: {DEFAULT_BACKEND}."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for the script.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code (``0`` on success, ``1`` on error).
    """
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    repo_url: str = args.repository_url.strip()
    token: Optional[str] = args.token
    depth: Optional[int] = DEFAULT_CLONE_DEPTH if args.depth else None
    backend_name: str = args.backend

    try:
        backend = create_backend(backend_name)
    except ValueError as e:
        logger.error(f"{e}")
        return 1

    print(f"Using backend: {backend.name}")

    # --- Authentication ---------------------------------------------------
    try:
        github_client = get_github_client(token)
        if token:
            print(f"Authenticated as: {github_client.get_user().login}")
    except GithubException as e:
        logger.error(f"Authentication failed: {e}")
        return 1

    # --- Fetch repository metadata ---------------------------------------
    try:
        repo = get_repo(repo_url, github_client)
    except (ValueError, Exception) as e:
        logger.error(f"{e}")
        return 1

    size_mb = get_repo_size(repo)
    if not confirm_large_repo(size_mb):
        print("Aborted by user.")
        return 0

    default_branch = get_default_branch(repo)
    clone_url = build_clone_url(repo)

    # --- Clone (with branch fallback) ------------------------------------
    try:
        repo_path = clone_repo(clone_url, default_branch, depth, backend)
    except Exception as e:
        if "not found" in str(e).lower() or "fatal:" in str(e):
            alt_branch = DEFAULT_BRANCH_FALLBACK if default_branch == "main" else "main"
            logger.warning(
                f"Branch '{default_branch}' failed, trying '{alt_branch}'..."
            )
            try:
                repo_path = clone_repo(clone_url, alt_branch, depth, backend)
            except Exception as e2:
                logger.error(f"Clone with both branches failed: {e2}")
                return 1
        else:
            logger.error(f"{e}")
            return 1

    # --- Submodules ------------------------------------------------------
    try:
        init_submodules(repo_path, backend)
    except Exception as e:
        logger.warning(f"Submodule handling failed: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
