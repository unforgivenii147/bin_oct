#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse


def clone_files(
    repo_url: str, output_dir: Path, extensions: list[str]
) -> tuple[str, bool, str]:
    try:
        parsed = urlparse(repo_url)
        repo_name = Path(parsed.path).stem
        repo_path = output_dir / repo_name
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
            timeout=300,
        )
        subprocess.run(
            ["git", "-C", str(repo_path), "sparse-checkout", "init", "--no-cone"],
            check=True,
            capture_output=True,
        )
        patterns = [
            f"**/*{ext if ext.startswith('.') else f'.{ext}'}" for ext in extensions
        ]
        subprocess.run(
            ["git", "-C", str(repo_path), "sparse-checkout", "set"] + patterns,
            check=True,
            capture_output=True,
        )
        return repo_url, True, f"Successfully cloned {repo_name}"
    except Exception as e:
        return repo_url, False, f"Failed: {e!s}"


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: python script.py <extension1> [extension2] ... <repo_url1> [repo_url2] ..."
        )
        print("Example: python script.py .py .txt .md https://github.com/user/repo.git")
        sys.exit(1)
    args = sys.argv[1:]
    extensions = []
    repo_urls = []
    for arg in args:
        if arg.startswith(("http://", "https://")) or arg.endswith(".git"):
            repo_urls.append(arg)
        else:
            extensions.append(arg)
    if not extensions or not repo_urls:
        print("Error: Must provide at least one extension and one repository URL")
        sys.exit(1)
    output_dir = Path.cwd() / "cloned_repos"
    output_dir.mkdir(exist_ok=True)
    print(f"Extensions to clone: {', '.join(extensions)}")
    print(f"Repositories: {len(repo_urls)}\n")
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(clone_files, url, output_dir, extensions): url
            for url in repo_urls
        }
        for future in as_completed(futures):
            url, success, message = future.result()
            status = "✓" if success else "✗"
            print(f"{status} {url}: {message}")


if __name__ == "__main__":
    raise SystemExit(main())
