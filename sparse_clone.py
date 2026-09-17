#!/data/data/com.termux/files/home/.local/bin/python
"""Clone Git repositories with sparse checkout for given file extensions: parse CLI args into extensions and repo URLs, clone each repo in a multiprocessing pool of 8 workers using `git --filter=blob:none --sparse`, and log results via loguru."""

import subprocess
import sys
from multiprocessing.pool import Pool
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

from loguru import logger

MAX_WORKERS: Final[int] = 8
CLONE_TIMEOUT_SECONDS: Final[int] = 300


def clone_files(
    args: tuple[str, Path, list[str]],
) -> tuple[str, bool, str]:
    """Sparse-clone a repository for the requested extensions.

    ``args`` is a ``(repo_url, output_dir, extensions)`` tuple because
    :meth:`multiprocessing.pool.Pool.imap_unordered` only forwards a single
    positional argument to the worker function.
    """
    repo_url, output_dir, extensions = args
    try:
        parsed = urlparse(repo_url)
        repo_name: str = Path(parsed.path).stem
        repo_path: Path = output_dir / repo_name

        subprocess.run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--sparse",
                repo_url,
                str(repo_path),
            ],
            check=True,
            capture_output=True,
            timeout=CLONE_TIMEOUT_SECONDS,
        )
        subprocess.run(
            ["git", "-C", str(repo_path), "sparse-checkout", "init", "--no-cone"],
            check=True,
            capture_output=True,
        )

        patterns: list[str] = [
            f"**/*{ext if ext.startswith('.') else f'.{ext}'}" for ext in extensions
        ]
        subprocess.run(
            ["git", "-C", str(repo_path), "sparse-checkout", "set", *patterns],
            check=True,
            capture_output=True,
        )
        return repo_url, True, f"Successfully cloned {repo_name}"
    except Exception as e:
        return repo_url, False, f"Failed: {e!s}"


def main() -> None:
    """CLI entry point: parse args and clone each repository in parallel."""
    if len(sys.argv) < 3:
        logger.error(
            "Usage: {} <extension1> [extension2] ... <repo_url1> [repo_url2] ...",
            Path(sys.argv[0]).name,
        )
        logger.info(
            "Example: python script.py .py .txt .md https://github.com/user/repo.git"
        )
        sys.exit(1)

    args: list[str] = sys.argv[1:]
    extensions: list[str] = []
    repo_urls: list[str] = []

    for arg in args:
        if arg.startswith(("http://", "https://")) or arg.endswith(".git"):
            repo_urls.append(arg)
        else:
            extensions.append(arg)

    if not extensions or not repo_urls:
        logger.error("Must provide at least one extension and one repository URL")
        sys.exit(1)

    output_dir: Path = Path.cwd() / "cloned_repos"
    output_dir.mkdir(exist_ok=True)

    logger.info("Extensions to clone: {}", ", ".join(extensions))
    logger.info("Repositories: {}", len(repo_urls))

    jobs: list[tuple[str, Path, list[str]]] = [
        (url, output_dir, extensions) for url in repo_urls
    ]

    with Pool(processes=MAX_WORKERS) as pool:
        for url, success, message in pool.imap_unordered(clone_files, jobs):
            status: str = "✓" if success else "✗"
            if success:
                logger.info("{} {}: {}", status, url, message)
            else:
                logger.error("{} {}: {}", status, url, message)


if __name__ == "__main__":
    raise SystemExit(main())
