#!/data/data/com.termux/files/home/.local/bin/python
"""
Clone GitHub repositories from a text file using multiprocessing.Pool with 8 workers.
Reads repository names in 'user/repo' format, clones them into the specified output
directory, and supports a dry-run mode. Uses loguru for logging and pathlib for paths.
"""

import argparse
import shutil
import sys
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path

from git import GitCommandError, Repo
from git.exc import InvalidGitRepositoryError
from loguru import logger


def read_repos(file_path: Path) -> list[str]:
    """
    Read repository names from a file, one per line.

    Args:
        file_path: Path to the file containing repository names.

    Returns:
        A list of repository strings (e.g., 'user/repo').

    Raises:
        SystemExit: If the file does not exist or contains no repositories.
    """
    if not file_path.exists():
        logger.error(f"Error: {file_path} does not exist")
        sys.exit(1)

    with file_path.open() as f:
        repos: list[str] = [line.strip() for line in f if line.strip()]

    if not repos:
        logger.error(f"Error: No repositories found in {file_path}")
        sys.exit(1)

    return repos


def validate_repo_format(repo: str) -> bool:
    """
    Check whether a repository string is in the 'user/repo' format.

    Args:
        repo: The repository string to validate.

    Returns:
        True if the format is valid, False otherwise.
    """
    parts: list[str] = repo.split("/")
    return len(parts) == 2 and all(parts)


def clone_repo(repo: str, base_dir: Path) -> tuple[str, bool, str]:
    """
    Clone a single GitHub repository into base_dir/user/repo.

    Args:
        repo: Repository identifier in 'user/repo' format.
        base_dir: Base directory where the repository will be cloned.

    Returns:
        A tuple of (repo, success, message). `success` is True if the repository
        already existed or was cloned successfully; otherwise False.
    """
    if not validate_repo_format(repo):
        return repo, False, f"Invalid format: {repo} (expected user/repo)"

    parts: list[str] = repo.split("/")
    user: str = parts[0]
    repo_name: str = parts[1]
    target_dir: Path = base_dir / user / repo_name

    if target_dir.exists():
        try:
            Repo(target_dir)
            return repo, True, f"Already exists: {target_dir}"
        except InvalidGitRepositoryError:
            return repo, False, f"Directory exists but is not a git repo: {target_dir}"

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    clone_url: str = f"https://github.com/{repo}.git"

    try:
        Repo.clone_from(clone_url, target_dir, depth=1, single_branch=True)
        return repo, True, f"Successfully cloned to {target_dir}"
    except GitCommandError as e:
        error_msg: str = str(e).strip()
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        return repo, False, f"Clone failed: {error_msg}"
    except Exception as e:
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        return repo, False, f"Error: {e!s}"


def main() -> None:
    """
    Parse command-line arguments and orchestrate the cloning process.
    """
    parser = argparse.ArgumentParser(
        description="Clone GitHub repositories in parallel from a text file"
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="repos.txt",
        help="Path to file containing repositories (default: repos.txt)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="repos",
        help="Output directory for cloned repositories (default: repos)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be cloned without actually cloning",
    )
    args: argparse.Namespace = parser.parse_args()

    repos_file: Path = Path(args.file)
    output_dir: Path = Path(args.output)

    repos: list[str] = read_repos(repos_file)
    print(f"Found {len(repos)} repositories to clone")

    if args.dry_run:
        print("\nDry run - would clone:")
        for repo in repos:
            if validate_repo_format(repo):
                parts: list[str] = repo.split("/")
                user: str = parts[0]
                repo_name: str = parts[1]
                target: Path = output_dir / user / repo_name
                status: str = "EXISTS" if target.exists() else "NEW"
                print(f"  [{status}] {repo} -> {target}")
            else:
                print(f"  [INVALID] {repo}")
        return

    successful: int = 0
    failed: int = 0
    skipped: int = 0

    print(f"\nCloning with 8 parallel workers to {output_dir.absolute()}")
    print("-" * 40)

    with Pool(processes=8) as pool:
        async_results: list[AsyncResult[tuple[str, bool, str]]] = [
            pool.apply_async(clone_repo, (repo, output_dir)) for repo in repos
        ]

        for repo, async_res in zip(repos, async_results):
            try:
                _, success, message = async_res.get()
                if success:
                    if "Already exists" in message:
                        skipped += 1
                        print(f"⏭️  {repo}: {message}")
                    else:
                        successful += 1
                        print(f"✅ {repo}: {message}")
                else:
                    failed += 1
                    print(f"❌ {repo}: {message}")
            except Exception as e:
                failed += 1
                logger.error(f"❌ {repo}: Unexpected error: {e!s}")

    print("-" * 40)
    print("\nSummary:")
    print(f"  ✅ Successfully cloned: {successful}")
    print(f"  ⏭️  Already existed: {skipped}")
    print(f"  ❌ Failed: {failed}")
    print(f"  📊 Total: {len(repos)}")


if __name__ == "__main__":
    raise SystemExit(main())
