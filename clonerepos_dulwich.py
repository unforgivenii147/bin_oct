#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that clones GitHub repositories listed in a text file.

The script reads repository names (one per line in `user/repo` format) from a
file, checks each repository's size via the GitHub API, skips repositories
larger than a configurable limit, and clones the remaining small repositories
in parallel using `dulwich` (pure Python). Cloning is performed with
`multiprocessing.Pool.apply_async` using a fixed pool of 8 workers. Cloned
repositories are placed under `<output>/<user>/<repo>`. After a successful
clone (or if the repository already exists as a git repo), the repository is
removed from the input file unless `--no-cleanup` is passed. A `--dry-run`
mode reports what would be done without cloning. Logging is done with
`loguru`, and all path handling uses `pathlib`.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Final

import requests
from dulwich import porcelain
from dulwich.errors import NotGitRepository
from dulwich.repo import Repo
from loguru import logger

MAX_SIZE_MB: Final[int] = 5
MAX_SIZE_BYTES: int = MAX_SIZE_MB * 1024 * 1024
DEFAULT_WORKERS: Final[int] = 8


def read_repos(path: Path) -> list[str]:
    """Read repository names from *path*, one per line, skipping blanks.

    Args:
        path: Path to the file containing repository names.

    Returns:
        A list of non-empty repository name strings.

    Raises:
        SystemExit: If the file does not exist or contains no repositories.
    """
    if not path.exists():
        logger.error(f"Error: {path} does not exist")
        sys.exit(1)
    with open(path) as f:
        repos: list[str] = [line.strip() for line in f if line.strip()]
    if not repos:
        logger.error(f"Error: No repositories found in {path}")
        sys.exit(1)
    return repos


def validate_repo_format(repo: str) -> bool:
    """Return True if *repo* is in the expected ``user/repo`` format."""
    parts: list[str] = repo.split("/")
    return len(parts) == 2 and all(parts)


def check_repo_size(repo: str) -> tuple[bool, int]:
    """Query the GitHub API for the size of *repo*.

    Args:
        repo: Repository in ``user/repo`` format.

    Returns:
        A tuple ``(is_small, size_bytes)``. ``is_small`` is True when the
        repository is within the configured size limit, or when the size
        cannot be determined (fail-open). ``size_bytes`` is 0 when unknown.
    """
    api_url: str = f"https://api.github.com/repos/{repo}"
    try:
        response = requests.get(api_url, timeout=10)
        if response.status_code == 200:
            data: dict[str, object] = response.json()
            size_kb_raw = data.get("size", 0)
            size_kb: int = (
                int(size_kb_raw) if isinstance(size_kb_raw, (int, float, str)) else 0
            )
            size_bytes: int = size_kb * 1024
            return size_bytes <= MAX_SIZE_BYTES, size_bytes
        return True, 0
    except Exception:
        return True, 0


def clone_repo(repo: str, base_dir: Path) -> tuple[str, bool, str]:
    """Clone a single repository into *base_dir*.

    Args:
        repo: Repository in ``user/repo`` format.
        base_dir: Parent directory under which ``<user>/<repo>`` is created.

    Returns:
        A tuple ``(repo, success, message)`` describing the outcome.
    """
    if not validate_repo_format(repo):
        return repo, False, f"Invalid format: {repo} (expected user/repo)"
    user, repo_name = repo.split("/")
    target_dir: Path = base_dir / user / repo_name
    if target_dir.exists():
        try:
            Repo(str(target_dir))
            return repo, True, f"Already exists: {target_dir}"
        except NotGitRepository:
            return repo, False, f"Directory exists but is not a git repo: {target_dir}"
    is_small, size_bytes = check_repo_size(repo)
    if not is_small:
        return repo, False, f"Too large ({fsz(size_bytes)} > {MAX_SIZE_MB}MB)"
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    clone_url: str = f"https://github.com/{repo}.git"
    try:
        porcelain.clone(clone_url, str(target_dir), depth=1, bare=False)
        return repo, True, f"Successfully cloned to {target_dir} ({fsz(size_bytes)})"
    except Exception as e:
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        return repo, False, f"Clone failed: {e!s}"


def remove_from_repos_file(path: Path, repos_to_remove: set[str]) -> None:
    """Remove *repos_to_remove* from the repository list file *path*."""
    if not repos_to_remove:
        return
    current_repos: list[str] = read_repos(path)
    updated_repos: list[str] = [
        repo for repo in current_repos if repo not in repos_to_remove
    ]
    with open(path, "w") as f:
        f.write("\n".join(updated_repos) + "\n" if updated_repos else "")
    print(f"\nRemoved {len(repos_to_remove)} repos from {path}")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Clone GitHub repositories using pure Python (dulwich)"
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="repos.txt",
        help="Path to file containing repositories (default: repos.txt)",
    )
    parser.add_argument(
        "-o", "--output", default="repos", help="Output directory (default: repos)"
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=MAX_SIZE_MB,
        help=f"Maximum repo size in MB (default: {MAX_SIZE_MB})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be cloned without actually cloning",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Don't remove cloned repos from repos.txt",
    )
    return parser.parse_args()


def main() -> int:
    """Entry point: read repos, clone in parallel, and report summary."""
    global MAX_SIZE_BYTES

    args: argparse.Namespace = parse_args()

    if args.max_size != MAX_SIZE_MB:
        MAX_SIZE_BYTES = args.max_size * 1024 * 1024

    repos_file: Path = Path(args.file)
    output_dir: Path = Path(args.output)
    repos: list[str] = read_repos(repos_file)

    print(f"Found {len(repos)} repositories to clone")
    print(f"Max repo size: {args.max_size}MB")

    if args.dry_run:
        print("\nDry run - checking sizes:")
        for repo in repos:
            if validate_repo_format(repo):
                user, repo_name = repo.split("/")
                target: Path = output_dir / user / repo_name
                is_small, size = check_repo_size(repo)
                if target.exists():
                    print(f"  [EXISTS] {repo} -> {target}")
                elif not is_small:
                    print(f"  [TOO LARGE] {repo} ({fsz(size)})")
                else:
                    print(f"  [OK] {repo} -> {target} ({fsz(size)})")
            else:
                print(f"  [INVALID] {repo}")
        return 0

    successful: int = 0
    failed: int = 0
    skipped: int = 0
    successfully_cloned: set[str] = set()

    print(
        f"\nCloning with {DEFAULT_WORKERS} parallel workers to {output_dir.absolute()}"
    )
    print("-" * 40)

    with Pool(processes=DEFAULT_WORKERS) as pool:
        async_results = [
            (repo, pool.apply_async(clone_repo, (repo, output_dir))) for repo in repos
        ]
        for repo, async_result in async_results:
            try:
                repo_name, success, message = async_result.get()
                if success:
                    if "Already exists" in message:
                        skipped += 1
                        print(f"⏭️  {repo}: {message}")
                        successfully_cloned.add(repo)
                    else:
                        successful += 1
                        print(f"✅ {repo}: {message}")
                        successfully_cloned.add(repo)
                else:
                    failed += 1
                    logger.error(f"❌ {repo}: {message}")
            except Exception as e:
                failed += 1
                logger.error(f"❌ {repo}: Unexpected error: {e!s}")

    if not args.no_cleanup and successfully_cloned:
        remove_from_repos_file(repos_file, successfully_cloned)

    print("-" * 40)
    print("\nSummary:")
    print(f"  ✅ Successfully cloned: {successful}")
    print(f"  ⏭️  Already existed: {skipped}")
    print(f"  ❌ Failed: {failed}")
    print(f"  📊 Total processed: {len(repos)}")
    if not args.no_cleanup and successfully_cloned:
        remaining: int = len(read_repos(repos_file))
        print(f"  📝 Remaining in {repos_file}: {remaining}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
