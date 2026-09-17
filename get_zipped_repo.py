#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from github import Github
from tqdm import tqdm

env_path = Path.home() / ".env"
load_dotenv(env_path)


def download_repo_zip(username, repo, branch="main", output_name=None):
    g = Github(os.getenv("GITHUB_TOKEN"))
    repo_obj = g.get_repo(f"{username}/{repo}")
    zip_url = repo_obj.get_zipball_url(branch)
    token = os.getenv("GITHUB_TOKEN")
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3.raw",
    }
    response = requests.get(zip_url, headers=headers, stream=True)
    response.raise_for_status()
    total_size = int(response.headers.get("content-length", 0))
    size_mb = total_size / (1024 * 1024)
    print(f"📦 Download size: {size_mb:.2f} MB ({total_size:,} bytes)")
    if output_name is None:
        output_name = f"{repo}-{branch}.zip"
    chunk_size = 8192
    with (
        open(output_name, "wb") as f,
        tqdm(total=total_size, unit="B", unit_scale=True, desc="Downloading") as pbar,
    ):
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
                pbar.update(len(chunk))
    print(f"✅ Downloaded: {output_name}")
    return output_name


def main():
    parser = argparse.ArgumentParser(description="Download a GitHub repository as ZIP")
    parser.add_argument("repo", help='Repository in format "username/repo"')
    parser.add_argument(
        "--branch", "-b", default="main", help="Branch name (default: main)"
    )
    parser.add_argument("--output", "-o", help="Output filename")
    args = parser.parse_args()
    try:
        username, repo = args.repo.split("/")
    except ValueError:
        print("❌ Error: Repository must be in format 'username/repo'")
        sys.exit(1)
    download_repo_zip(username, repo, args.branch, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
