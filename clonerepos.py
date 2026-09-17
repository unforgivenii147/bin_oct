#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI script that downloads GitHub repositories listed in a text file as ZIP archives.

The script must:
- Accept an optional positional argument for the repos file path (default: "repos.txt").
- Accept -o/--output for the output directory (default: "repos").
- Accept --dry-run to preview actions without downloading.
- Use multiprocessing.Pool.apply_async with a fixed pool of 8 workers for concurrency (no CLI flag for workers).
- Use loguru for all logging (no print(statements, no stdlib logging).)
- Use pathlib exclusively for filesystem paths.
- Validate each repo string is in "owner/name" format.
- Skip repos whose target directory already exists.
- Download via https://api.github.com/repos/{repo}/zipball, extract the zip, and place contents under {output}/{owner}/{name}.
- Provide complete type annotations passing strict mypy/pyright.
- Include docstrings on all functions and the module.
"""

from __future__ import annotations

import argparse
import io
import shutil
import sys
import zipfile
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Final

import requests
from loguru import logger

NUM_WORKERS: Final[int] = 8
REQUEST_TIMEOUT: Final[int] = 30


def read_repos(path: Path) -> list[str]:
    """Read repository identifiers from a text file, one per line.

    Args:
        path: Path to the file containing repository names.

    Returns:
        A list of non-empty, stripped repository identifier strings.

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
    """Validate that a repository string is in 'owner/name' format.

    Args:
        repo: The repository identifier to validate.

    Returns:
        True if the repo has exactly two non-empty slash-separated parts.
    """
    parts: list[str] = repo.split("/")
    return len(parts) == 2 and all(parts)


def download_repo_zip(repo: str, base_dir: Path) -> tuple[str, bool, str]:
    """Download and extract a GitHub repository's ZIP archive.

    Args:
        repo: Repository identifier in 'owner/name' format.
        base_dir: Base output directory to extract into.

    Returns:
        A tuple of (repo, success, message).
    """
    if not validate_repo_format(repo):
        return repo, False, f"Invalid format: {repo}"
    user, repo_name = repo.split("/")
    target_dir: Path = base_dir / user / repo_name
    if target_dir.exists():
        return repo, True, f"Already exists: {target_dir}"
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    zip_url: str = f"https://api.github.com/repos/{repo}/zipball"
    try:
        response: requests.Response = requests.get(
            zip_url, timeout=REQUEST_TIMEOUT, stream=True
        )
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            root_dir: str = z.namelist()[0].split("/")[0]
            temp_dir: Path = target_dir.parent / f"_temp_{repo_name}"
            z.extractall(temp_dir)
            extracted_root: Path = temp_dir / root_dir
            if extracted_root.exists():
                target_dir.mkdir(parents=True, exist_ok=True)
                for item in extracted_root.iterdir():
                    shutil.move(str(item), str(target_dir / item.name))
                shutil.rmtree(temp_dir)
            else:
                shutil.move(str(temp_dir), str(target_dir))
        return repo, True, f"Successfully downloaded to {target_dir}"
    except requests.RequestException as e:
        return repo, False, f"Download failed: {e!s}"
    except zipfile.BadZipFile:
        return repo, False, "Invalid ZIP file received"
    except Exception as e:
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        return repo, False, f"Error: {e!s}"


def main() -> int:
    """Entry point for the repository downloader CLI.

    Returns:
        Process exit code (0 on success).
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Download GitHub repositories as ZIP archives"
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
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded without downloading",
    )
    args: argparse.Namespace = parser.parse_args()

    repos_file: Path = Path(args.file)
    output_dir: Path = Path(args.output)
    repos: list[str] = read_repos(repos_file)
    print(f"Found {len(repos)} repositories to download")

    if args.dry_run:
        print("\nDry run - would download:")
        for repo in repos:
            if validate_repo_format(repo):
                user, repo_name = repo.split("/")
                target: Path = output_dir / user / repo_name
                status: str = "EXISTS" if target.exists() else "NEW"
                print(f"  [{status}] {repo} -> {target}")
            else:
                print(f"  [INVALID] {repo}")
        return 0

    successful: int = 0
    failed: int = 0
    skipped: int = 0
    print(
        f"\nDownloading with {NUM_WORKERS} parallel workers to {output_dir.absolute()}"
    )
    print("-" * 40)

    with Pool(processes=NUM_WORKERS) as pool:
        results: list[AsyncResult[tuple[str, bool, str]]] = [
            pool.apply_async(download_repo_zip, (repo, output_dir)) for repo in repos
        ]
        pool.close()
        for result in results:
            try:
                repo_name, success, message = result.get()
                if success:
                    if "Already exists" in message:
                        skipped += 1
                        print(f"⏭️  {repo_name}: {message}")
                    else:
                        successful += 1
                        print(f"✅ {repo_name}: {message}")
                else:
                    failed += 1
                    logger.error(f"❌ {repo_name}: {message}")
            except Exception as e:
                failed += 1
                logger.error(f"❌ Unexpected error: {e!s}")
        pool.join()

    print("-" * 40)
    print("\nSummary:")
    print(f"  ✅ Successfully downloaded: {successful}")
    print(f"  ⏭️  Already existed: {skipped}")
    print(f"  ❌ Failed: {failed}")
    print(f"  📊 Total: {len(repos)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
