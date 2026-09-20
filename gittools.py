#!/data/data/com.termux/files/home/.local/bin/python
"""GitHub repository toolkit — one CLI for all the original scripts.

Subcommands
-----------
clone      Parallel `git clone` (GitPython) of a repo list file.
zip        Parallel ZIP download via GitHub's /zipball API (requests).
dulwich    Pure-Python clone via dulwich with size limit + optional cleanup.
fork       Fork a GitHub repo and clone the fork (adds `upstream` remote).
gclone     Size-filtered single-shot clone of every entry in repos.txt.
get-zip    Download one repo as a ZIP (token + progress bar).
sparse     Sparse-checkout clone filtered by file extensions.

Mapping from the original scripts
---------------------------------
  clone_repos.py         ->  python repotools.py clone
  clonerepos.py          ->  python repotools.py zip
  clonerepos_dulwich.py  ->  python repotools.py dulwich
  forklone.py            ->  python repotools.py fork <user/repo>
  gclone1.py             ->  python repotools.py gclone
  get_zipped_repo.py     ->  python repotools.py get-zip <user/repo>
  sparse_clone.py        ->  python repotools.py sparse <ext>... <url>...

Third-party packages (install the ones you need):
  requests, loguru                 (all subcommands)
  GitPython   (`clone`, `fork`)    -> `pip install gitpython`
  dulwich     (`dulwich`)          -> `pip install dulwich`
  PyGithub    (`fork`, `get-zip`)  -> `pip install PyGithub`
  python-dotenv (`fork`, `get-zip`)-> `pip install python-dotenv`
  tqdm        (`get-zip`)          -> `pip install tqdm`
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import Pool
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

import requests
from loguru import logger


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _load_repo_list(file_path: Path) -> list[str]:
    """Return the non-empty, stripped lines of *file_path* or exit(1)."""
    if not file_path.exists():
        logger.error(f"Error: {file_path} does not exist")
        sys.exit(1)
    with file_path.open() as fh:
        repos = [line.strip() for line in fh if line.strip()]
    if not repos:
        logger.error(f"Error: No repositories found in {file_path}")
        sys.exit(1)
    return repos


def _is_valid_slug(slug: str) -> bool:
    """True if *slug* looks like ``owner/repo``."""
    parts = slug.split("/")
    return len(parts) == 2 and all(parts)


def _human_size(n: int) -> str:
    """Format a byte count in a compact human-readable form."""
    if n < 1024:
        return f"{n}B"
    if n < 1024**2:
        return f"{n / 1024:.1f}KB"
    if n < 1024**3:
        return f"{n / 1024**2:.1f}MB"
    return f"{n / 1024**3:.2f}GB"


def _print_summary(
    success: int,
    existed: int,
    failed: int,
    total: int,
    success_label: str = "Successfully cloned",
) -> None:
    """Print a uniform end-of-run summary block."""
    print("-" * 40)
    print("\nSummary:")
    print(f"  ✅ {success_label}: {success}")
    print(f"  ⏭️  Already existed: {existed}")
    print(f"  ❌ Failed: {failed}")
    print(f"  📊 Total: {total}")


def _pool_consume(
    pool: Pool,
    jobs: list[tuple[str, object]],
    result_handler: Callable[[str, bool, str], None],
) -> None:
    """Run ``(slug, async_result)`` pairs to completion, calling *result_handler*."""
    for slug, async_res in jobs:
        try:
            _, ok, msg = async_res.get()
            result_handler(slug, ok, msg)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"❌ {slug}: Unexpected error: {exc!s}")


def _load_dotenv_token(quiet: bool = False) -> Optional[str]:
    """Load GITHUB_TOKEN from ~/.env (same behaviour as forklone.py)."""
    from dotenv import load_dotenv

    env_path = Path.home() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        token = os.getenv("GITHUB_TOKEN")
        if token:
            if not quiet:
                print(f"✓ Loaded GITHUB_TOKEN from {env_path}")
            return token
        if not quiet:
            print(f"⚠️  {env_path} exists but GITHUB_TOKEN not found")
    elif not quiet:
        print("⚠️  ~/.env file not found")
    return None


def _gh_size_mb(owner: str, repo: str, token: Optional[str] = None) -> Optional[float]:
    """Return the repo size in MB according to the GitHub API, or None on error."""
    url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        size = data.get("size")
        if size is None:
            print(f"⚠️ Warning: Could not retrieve size for {owner}/{repo} from API.")
            return None
        return round(size / 1024.0, 2)
    except requests.exceptions.HTTPError as exc:
        print(f"❌ API Error: {exc.response.status_code} for {owner}/{repo}")
        if exc.response.status_code == 404:
            print("   Repository not found or access denied.")
        elif exc.response.status_code == 403:
            print("   Rate limit exceeded or insufficient permissions.")
        else:
            print(f"   Response: {exc.response.text}")
    except requests.exceptions.RequestException as exc:
        print(f"❌ Network Error: Could not connect to GitHub API: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"❌ An unexpected error occurred while fetching size: {exc}")
    return None


# ---------------------------------------------------------------------------
# clone  (originally clone_repos.py)
# ---------------------------------------------------------------------------


def _git_clone_one(slug: str, output_dir: Path) -> tuple[str, bool, str]:
    """Worker: shallow-clone ``owner/repo`` into ``output_dir/owner/repo``."""
    from git import GitCommandError, Repo
    from git.exc import InvalidGitRepositoryError

    if not _is_valid_slug(slug):
        return slug, False, f"Invalid format: {slug} (expected user/repo)"

    owner, repo = slug.split("/")
    dest = output_dir / owner / repo

    if dest.exists():
        try:
            Repo(dest)
            return slug, True, f"Already exists: {dest}"
        except InvalidGitRepositoryError:
            return slug, False, f"Directory exists but is not a git repo: {dest}"

    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{slug}.git"
    try:
        Repo.clone_from(url, dest, depth=1, single_branch=True)
        return slug, True, f"Successfully cloned to {dest}"
    except GitCommandError as exc:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        return slug, False, f"Clone failed: {str(exc).strip()}"
    except Exception as exc:  # noqa: BLE001
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        return slug, False, f"Error: {exc!s}"


def cmd_clone(args: argparse.Namespace) -> int:
    repo_file = Path(args.file)
    out_dir = Path(args.output)
    repos = _load_repo_list(repo_file)

    print(f"Found {len(repos)} repositories to clone")

    if args.dry_run:
        print("\nDry run - would clone:")
        for slug in repos:
            if _is_valid_slug(slug):
                owner, repo = slug.split("/")
                dest = out_dir / owner / repo
                flag = "EXISTS" if dest.exists() else "NEW"
                print(f"  [{flag}] {slug} -> {dest}")
            else:
                print(f"  [INVALID] {slug}")
        return 0

    counters = {"ok": 0, "existed": 0, "failed": 0}

    def handle(slug: str, ok: bool, msg: str) -> None:
        if ok and "Already exists" in msg:
            counters["existed"] += 1
            print(f"⏭️  {slug}: {msg}")
        elif ok:
            counters["ok"] += 1
            print(f"✅ {slug}: {msg}")
        else:
            counters["failed"] += 1
            print(f"❌ {slug}: {msg}")

    print(f"\nCloning with {args.workers} parallel workers to {out_dir.absolute()}")
    print("-" * 40)

    with Pool(processes=args.workers) as pool:
        jobs = [
            (slug, pool.apply_async(_git_clone_one, (slug, out_dir))) for slug in repos
        ]
        _pool_consume(pool, jobs, handle)

    _print_summary(counters["ok"], counters["existed"], counters["failed"], len(repos))
    return 0


# ---------------------------------------------------------------------------
# zip  (originally clonerepos.py)
# ---------------------------------------------------------------------------


def _zip_download_one(
    slug: str, output_dir: Path, timeout: int
) -> tuple[str, bool, str]:
    """Worker: download ``owner/repo`` as a ZIP archive and extract it."""
    if not _is_valid_slug(slug):
        return slug, False, f"Invalid format: {slug}"

    owner, repo = slug.split("/")
    dest = output_dir / owner / repo
    if dest.exists():
        return slug, True, f"Already exists: {dest}"

    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://api.github.com/repos/{slug}/zipball"
    try:
        resp = requests.get(url, timeout=timeout, stream=True)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            top_dir = zf.namelist()[0].split("/")[0]
            tmp = dest.parent / f"_temp_{repo}"
            zf.extractall(tmp)
            inner = tmp / top_dir
            if inner.exists():
                dest.mkdir(parents=True, exist_ok=True)
                for item in inner.iterdir():
                    shutil.move(str(item), str(dest / item.name))
                shutil.rmtree(tmp)
            else:
                shutil.move(str(tmp), str(dest))
        return slug, True, f"Successfully downloaded to {dest}"
    except requests.RequestException as exc:
        return slug, False, f"Download failed: {exc!s}"
    except zipfile.BadZipFile:
        return slug, False, "Invalid ZIP file received"
    except Exception as exc:  # noqa: BLE001
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        return slug, False, f"Error: {exc!s}"


def cmd_zip(args: argparse.Namespace) -> int:
    repo_file = Path(args.file)
    out_dir = Path(args.output)
    repos = _load_repo_list(repo_file)

    print(f"Found {len(repos)} repositories to download")

    if args.dry_run:
        print("\nDry run - would download:")
        for slug in repos:
            if _is_valid_slug(slug):
                owner, repo = slug.split("/")
                dest = out_dir / owner / repo
                flag = "EXISTS" if dest.exists() else "NEW"
                print(f"  [{flag}] {slug} -> {dest}")
            else:
                print(f"  [INVALID] {slug}")
        return 0

    counters = {"ok": 0, "existed": 0, "failed": 0}

    def handle(slug: str, ok: bool, msg: str) -> None:
        if ok and "Already exists" in msg:
            counters["existed"] += 1
            print(f"⏭️  {slug}: {msg}")
        elif ok:
            counters["ok"] += 1
            print(f"✅ {slug}: {msg}")
        else:
            counters["failed"] += 1
            logger.error(f"❌ {slug}: {msg}")

    print(f"\nDownloading with {args.workers} parallel workers to {out_dir.absolute()}")
    print("-" * 40)

    with Pool(processes=args.workers) as pool:
        jobs = [
            (slug, pool.apply_async(_zip_download_one, (slug, out_dir, args.timeout)))
            for slug in repos
        ]
        _pool_consume(pool, jobs, handle)
        pool.close()
        pool.join()

    _print_summary(
        counters["ok"],
        counters["existed"],
        counters["failed"],
        len(repos),
        success_label="Successfully downloaded",
    )
    return 0


# ---------------------------------------------------------------------------
# dulwich  (originally clonerepos_dulwich.py)
# ---------------------------------------------------------------------------


def _dulwich_size_check(slug: str, max_bytes: int) -> tuple[bool, int]:
    """Return (fits_in_limit, size_in_bytes). Defaults to (True, 0) on error."""
    url = f"https://api.github.com/repos/{slug}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            raw = resp.json().get("size", 0)
            size_kb = int(raw) if isinstance(raw, (int, float, str)) else 0
            size_bytes = size_kb * 1024
            return size_bytes <= max_bytes, size_bytes
        return True, 0
    except Exception:  # noqa: BLE001
        return True, 0


def _dulwich_clone_one(
    slug: str, output_dir: Path, max_bytes: int
) -> tuple[str, bool, str]:
    """Worker: pure-Python clone via dulwich, respecting *max_bytes*."""
    from dulwich import porcelain
    from dulwich.errors import NotGitRepository
    from dulwich.repo import Repo as DulwichRepo

    if not _is_valid_slug(slug):
        return slug, False, f"Invalid format: {slug} (expected user/repo)"

    owner, repo = slug.split("/")
    dest = output_dir / owner / repo

    if dest.exists():
        try:
            DulwichRepo(str(dest))
            return slug, True, f"Already exists: {dest}"
        except NotGitRepository:
            return slug, False, f"Directory exists but is not a git repo: {dest}"

    fits, size_bytes = _dulwich_size_check(slug, max_bytes)
    if not fits:
        return (
            slug,
            False,
            f"Too large ({_human_size(size_bytes)} > {max_bytes // (1024 * 1024)}MB)",
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{slug}.git"
    try:
        porcelain.clone(url, str(dest), depth=1, bare=False)
        return slug, True, f"Successfully cloned to {dest} ({_human_size(size_bytes)})"
    except Exception as exc:  # noqa: BLE001
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        return slug, False, f"Clone failed: {exc!s}"


def cmd_dulwich(args: argparse.Namespace) -> int:
    repo_file = Path(args.file)
    out_dir = Path(args.output)
    max_bytes = args.max_size * 1024 * 1024
    repos = _load_repo_list(repo_file)

    print(f"Found {len(repos)} repositories to clone")
    print(f"Max repo size: {args.max_size}MB")

    if args.dry_run:
        print("\nDry run - checking sizes:")
        for slug in repos:
            if _is_valid_slug(slug):
                owner, repo = slug.split("/")
                dest = out_dir / owner / repo
                fits, size = _dulwich_size_check(slug, max_bytes)
                if dest.exists():
                    print(f"  [EXISTS] {slug} -> {dest}")
                elif not fits:
                    print(f"  [TOO LARGE] {slug} ({_human_size(size)})")
                else:
                    print(f"  [OK] {slug} -> {dest} ({_human_size(size)})")
            else:
                print(f"  [INVALID] {slug}")
        return 0

    counters = {"ok": 0, "existed": 0, "failed": 0}
    success_slugs: set[str] = set()

    def handle(slug: str, ok: bool, msg: str) -> None:
        if ok and "Already exists" in msg:
            counters["existed"] += 1
            print(f"⏭️  {slug}: {msg}")
            success_slugs.add(slug)
        elif ok:
            counters["ok"] += 1
            print(f"✅ {slug}: {msg}")
            success_slugs.add(slug)
        else:
            counters["failed"] += 1
            logger.error(f"❌ {slug}: {msg}")

    print(f"\nCloning with {args.workers} parallel workers to {out_dir.absolute()}")
    print("-" * 40)

    with Pool(processes=args.workers) as pool:
        jobs = [
            (slug, pool.apply_async(_dulwich_clone_one, (slug, out_dir, max_bytes)))
            for slug in repos
        ]
        _pool_consume(pool, jobs, handle)

    if not args.no_cleanup and success_slugs:
        remaining = [r for r in _load_repo_list(repo_file) if r not in success_slugs]
        repo_file.write_text("\n".join(remaining) + ("\n" if remaining else ""))
        print(f"\nRemoved {len(success_slugs)} repos from {repo_file}")

    _print_summary(counters["ok"], counters["existed"], counters["failed"], len(repos))
    if not args.no_cleanup and success_slugs:
        print(f"  📝 Remaining in {repo_file}: {len(_load_repo_list(repo_file))}")
    return 0


# ---------------------------------------------------------------------------
# fork  (originally forklone.py)
# ---------------------------------------------------------------------------


def _ensure_env_template() -> bool:
    """Create a ~/.env template if missing; returns False when it was created."""
    env_path = Path.home() / ".env"
    if not env_path.exists():
        print("\n📝 Creating ~/.env template...")
        env_path.write_text(
            "# GitHub Personal Access Token\n"
            "# Get one at: https://github.com/settings/tokens\n"
            "# Required scopes: repo, public_repo\n"
            "GITHUB_TOKEN=your_token_here\n"
        )
        print(f"✓ Created {env_path}")
        print("⚠️  Please edit the file and add your actual token")
        return False
    return True


def _print_token_help() -> None:
    print("\nGitHub token required")
    print("Please add to ~/.env file:")
    print("GITHUB_TOKEN=your_token_here")
    print("\nOr set environment variable:")
    print("  export GITHUB_TOKEN=your_token_here")
    print("\nGet a token at: https://github.com/settings/tokens")
    print("Required scope: 'repo' for private repos or 'public_repo' for public")


def _gh_authenticate(token: Optional[str]):
    """Return (Github client, authenticated user) or exit(1)."""
    from github import Github
    from github.GithubException import GithubException

    if not token:
        _print_token_help()
        sys.exit(1)
    try:
        gh = Github(token)
        user = gh.get_user()
        print(f"✓ Authenticated as: {user.login}")
        return gh, user
    except GithubException as exc:
        print(f"Authentication failed: {exc}")
        sys.exit(1)


def _gh_fork_repo(gh, user, origin_slug: str):
    """Return the (existing or freshly-created) fork of *origin_slug*."""
    from github.GithubException import GithubException, UnknownObjectException

    try:
        original = gh.get_repo(origin_slug)
        print(f"✓ Found original repo: {original.full_name}")
        try:
            existing = user.get_repo(original.name)
            print(f"✓ Repository already forked: {existing.clone_url}")
            return existing
        except UnknownObjectException:
            print(f"Forking {origin_slug}...")
            fork = original.create_fork()
            print(f"✓ Fork created: {fork.clone_url}")
            return fork
    except GithubException as exc:
        print(f"Error forking repository: {exc}")
        sys.exit(1)


def _clone_fork_and_link(fork, origin_slug: str):
    """Clone *fork* and add the *origin_slug* as `upstream`, wiring the branch."""
    from git import Repo

    repo_name = fork.name
    clone_url = fork.clone_url
    print(f"\nCloning {clone_url}...")
    try:
        local = Repo.clone_from(clone_url, repo_name)
        print(f"✓ Cloned to: ./{repo_name}")
    except Exception as exc:  # noqa: BLE001
        print(f"Error cloning: {exc}")
        sys.exit(1)

    upstream_url = f"https://github.com/{origin_slug}.git"
    print(f"Adding upstream remote: {upstream_url}")
    upstream = local.create_remote("upstream", upstream_url)
    default_branch = fork.default_branch
    print("Fetching from upstream...")
    upstream.fetch()
    local.git.branch(f"--set-upstream-to=upstream/{default_branch}", default_branch)
    return local, default_branch


def cmd_fork(args: argparse.Namespace) -> int:
    raw = args.repo
    if raw.startswith("https://github.com/"):
        slug = raw.replace("https://github.com/", "").rstrip("/")
    else:
        slug = raw
    if "/" not in slug:
        print("Error: Use format 'user/repo'")
        print("Example: octocat/Hello-World")
        sys.exit(1)

    _ensure_env_template()
    token = _load_dotenv_token()
    gh, user = _gh_authenticate(token)
    fork = _gh_fork_repo(gh, user, slug)
    local_repo, default_branch = _clone_fork_and_link(fork, slug)

    print("\n✓ Setup complete!")
    print("\nRemotes configured:")
    for remote in local_repo.remotes:
        print(f"  {remote.name}: {remote.url}")
    print(f"\nTo pull from original repo: git pull upstream {default_branch}")
    print(f"To push to your fork: git push origin {default_branch}")
    print(f"\nRepo location: ./{fork.name}")
    print("\nRepository info:")
    print(f"  Original: {slug}")
    print(f"  Your fork: {fork.full_name}")
    print(f"  Default branch: {default_branch}")
    return 0


# ---------------------------------------------------------------------------
# gclone  (originally gclone1.py)
# ---------------------------------------------------------------------------


def _parse_gh_slug(text: str) -> tuple[Optional[str], Optional[str]]:
    """Accept ``owner/repo`` or a GitHub URL; return (owner, repo) or (None, None)."""
    text = text.strip()
    if "/" in text and not text.startswith("http"):
        parts = text.split("/")
        if len(parts) == 2 and parts[0] and parts[1]:
            return parts[0], parts[1]
        return None, None
    try:
        parsed = urlparse(text)
        if parsed.netloc.lower() in {"github.com", "www.github.com"}:
            bits = [p for p in parsed.path.split("/") if p]
            if len(bits) == 2:
                return bits[0], bits[1]
    except Exception:  # noqa: BLE001
        pass
    return None, None


def _cli_git_clone(owner: str, repo: str, destination: Path) -> bool:
    """Shallow ``git clone`` via the CLI, mirroring gclone1.py."""
    slug = f"{owner}/{repo}"
    url = f"https://github.com/{slug}.git"
    print(f"\n🚀 Cloning {slug} (shallow clone)...")
    try:
        subprocess.run(["git", "clone", url, str(destination)], check=True)
        print("✅ Successfully cloned repository.")
        print(f"   Cloned into: {destination}")
        return True
    except FileNotFoundError:
        print(
            "❌ Error: 'git' command not found. Please ensure Git is installed and in your PATH."
        )
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"❌ An unexpected error occurred during cloning: {exc}")
        return False


def cmd_gclone(args: argparse.Namespace) -> int:
    repo_file = Path(args.file)
    lines = repo_file.read_text(encoding="utf-8").splitlines(keepends=False)
    token = args.token or os.getenv("GITHUB_TOKEN")
    too_large: list[str] = []

    total = len(lines)
    for idx, line in enumerate(lines):
        print(f"{idx}/{total}")
        owner, repo = _parse_gh_slug(line)
        if not owner or not repo:
            print(f"❌ Invalid GitHub repository format: '{line}'")
            too_large.append(line)
            continue

        print(f"🔍 Analyzing repository: {owner}/{repo}")
        size_mb = _gh_size_mb(owner, repo, token)
        if size_mb is not None and size_mb <= args.max_size:
            print(f"ℹ️ size: {size_mb} MB")
            destination = Path.cwd() / repo
            if destination.exists():
                print(f"⚠️  Destination already exists: {destination}")
                continue
            _cli_git_clone(owner, repo, destination)
        else:
            if size_mb is not None:
                print(f"⏭️  Skipping (size {size_mb} MB > {args.max_size} MB)")
            too_large.append(line)

    remaining_file = Path(args.remaining_file)
    remaining_file.write_text("\n".join(too_large), encoding="utf-8")
    print(f"\n📝 Wrote {len(too_large)} remaining entries to {remaining_file}")
    return 0


# ---------------------------------------------------------------------------
# get-zip  (originally get_zipped_repo.py)
# ---------------------------------------------------------------------------


def _download_zip_with_progress(
    owner: str, repo: str, branch: str, output: Optional[str]
) -> str:
    """Stream a repo zipball to disk with a tqdm progress bar."""
    from github import Github
    from tqdm import tqdm

    gh = Github(os.getenv("GITHUB_TOKEN"))
    gh_repo = gh.get_repo(f"{owner}/{repo}")
    zip_url = gh_repo.get_zipball_url(branch)

    token = os.getenv("GITHUB_TOKEN")
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3.raw",
    }
    resp = requests.get(zip_url, headers=headers, stream=True)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    print(f"📦 Download size: {total / (1024 * 1024):.2f} MB ({total:,} bytes)")

    out_name = output or f"{repo}-{branch}.zip"
    chunk = 8192
    with (
        open(out_name, "wb") as fh,
        tqdm(total=total, unit="B", unit_scale=True, desc="Downloading") as bar,
    ):
        for piece in resp.iter_content(chunk_size=chunk):
            if piece:
                fh.write(piece)
                bar.update(len(piece))
    print(f"✅ Downloaded: {out_name}")
    return out_name


def cmd_get_zip(args: argparse.Namespace) -> int:
    # Preserve original behaviour: dotenv is loaded at module import time.
    try:
        from dotenv import load_dotenv

        load_dotenv(Path.home() / ".env")
    except Exception:  # noqa: BLE001
        pass

    try:
        owner, repo = args.repo.split("/")
    except ValueError:
        print("❌ Error: Repository must be in format 'username/repo'")
        sys.exit(1)
    _download_zip_with_progress(owner, repo, args.branch, args.output)
    return 0


# ---------------------------------------------------------------------------
# sparse  (originally sparse_clone.py)
# ---------------------------------------------------------------------------


def _sparse_clone_one(
    url: str, output_dir: Path, extensions: list[str], timeout: int = 300
) -> tuple[str, bool, str]:
    """Worker: sparse-checkout clone of *url* limited to *extensions*."""
    try:
        parsed = urlparse(url)
        name = Path(parsed.path).stem
        dest = output_dir / name

        subprocess.run(
            ["git", "clone", "--filter=blob:none", "--sparse", url, str(dest)],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
        subprocess.run(
            ["git", "-C", str(dest), "sparse-checkout", "init", "--no-cone"],
            check=True,
            capture_output=True,
        )
        patterns = [
            f"**/*{(ext if ext.startswith('.') else '.' + ext)}" for ext in extensions
        ]
        subprocess.run(
            ["git", "-C", str(dest), "sparse-checkout", "set", *patterns],
            check=True,
            capture_output=True,
        )
        return url, True, f"Successfully cloned {name}"
    except Exception as exc:  # noqa: BLE001
        return url, False, f"Failed: {exc!s}"


def cmd_sparse(args: argparse.Namespace) -> int:
    tokens = args.items
    extensions: list[str] = []
    urls: list[str] = []
    for token in tokens:
        if token.startswith(("http://", "https://")) or token.endswith(".git"):
            urls.append(token)
        else:
            extensions.append(token)

    if not extensions or not urls:
        print("Error: Must provide at least one extension and one repository URL")
        return 1

    out_dir = Path(args.output)
    out_dir.mkdir(exist_ok=True)

    print(f"Extensions to clone: {', '.join(extensions)}")
    print(f"Repositories: {len(urls)}\n")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_sparse_clone_one, url, out_dir, extensions): url
            for url in urls
        }
        for future in as_completed(futures):
            url, ok, msg = future.result()
            print(f"{'✓' if ok else '✗'} {url}: {msg}")
    return 0


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repotools",
        description="Unified GitHub repository toolkit (clone / zip / dulwich / fork / gclone / get-zip / sparse).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Mappings to the original scripts:\n"
            "  clone_repos.py         -> repotools clone\n"
            "  clonerepos.py          -> repotools zip\n"
            "  clonerepos_dulwich.py  -> repotools dulwich\n"
            "  forklone.py            -> repotools fork <user/repo>\n"
            "  gclone1.py             -> repotools gclone\n"
            "  get_zipped_repo.py     -> repotools get-zip <user/repo>\n"
            "  sparse_clone.py        -> repotools sparse <ext>... <url>...\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # clone --------------------------------------------------------------
    p_clone = sub.add_parser("clone", help="Parallel git clone (GitPython).")
    p_clone.add_argument(
        "file",
        nargs="?",
        default="repos.txt",
        help="File with user/repo entries (default: repos.txt)",
    )
    p_clone.add_argument(
        "-o", "--output", default="repos", help="Output directory (default: repos)"
    )
    p_clone.add_argument(
        "-w", "--workers", type=int, default=8, help="Parallel workers (default: 8)"
    )
    p_clone.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be cloned without cloning",
    )
    p_clone.set_defaults(func=cmd_clone)

    # zip ----------------------------------------------------------------
    p_zip = sub.add_parser("zip", help="Parallel ZIP download via GitHub API.")
    p_zip.add_argument("file", nargs="?", default="repos.txt")
    p_zip.add_argument("-o", "--output", default="repos")
    p_zip.add_argument("-w", "--workers", type=int, default=8)
    p_zip.add_argument(
        "--timeout", type=int, default=30, help="HTTP timeout in seconds (default: 30)"
    )
    p_zip.add_argument("--dry-run", action="store_true")
    p_zip.set_defaults(func=cmd_zip)

    # dulwich ------------------------------------------------------------
    p_dul = sub.add_parser(
        "dulwich", help="Pure-Python clone via dulwich with size limit."
    )
    p_dul.add_argument("file", nargs="?", default="repos.txt")
    p_dul.add_argument("-o", "--output", default="repos")
    p_dul.add_argument("-w", "--workers", type=int, default=8)
    p_dul.add_argument(
        "--max-size", type=int, default=5, help="Maximum repo size in MB (default: 5)"
    )
    p_dul.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Do not remove successfully cloned repos from the list file",
    )
    p_dul.add_argument("--dry-run", action="store_true")
    p_dul.set_defaults(func=cmd_dulwich)

    # fork ---------------------------------------------------------------
    p_fork = sub.add_parser("fork", help="Fork a repo on GitHub and clone the fork.")
    p_fork.add_argument("repo", help="user/repo or full GitHub URL")
    p_fork.set_defaults(func=cmd_fork)

    # gclone -------------------------------------------------------------
    p_gc = sub.add_parser(
        "gclone", help="Size-filtered clone of every entry in repos.txt."
    )
    p_gc.add_argument("file", nargs="?", default="repos.txt")
    p_gc.add_argument(
        "--max-size",
        type=int,
        default=100,
        help="Maximum repo size in MB (default: 100)",
    )
    p_gc.add_argument(
        "--token", default=None, help="GitHub token (defaults to GITHUB_TOKEN env var)"
    )
    p_gc.add_argument(
        "--remaining-file",
        default="remained",
        help="Where to write entries that were skipped (default: remained)",
    )
    p_gc.set_defaults(func=cmd_gclone)

    # get-zip ------------------------------------------------------------
    p_gz = sub.add_parser("get-zip", help="Download one repo as a ZIP archive.")
    p_gz.add_argument("repo", help="user/repo")
    p_gz.add_argument(
        "--branch", "-b", default="main", help="Branch name (default: main)"
    )
    p_gz.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output filename (default: <repo>-<branch>.zip)",
    )
    p_gz.set_defaults(func=cmd_get_zip)

    # sparse -------------------------------------------------------------
    p_sp = sub.add_parser(
        "sparse", help="Sparse checkout clone filtered by extensions."
    )
    p_sp.add_argument(
        "items", nargs="+", help="Extensions (e.g. .py) and repository URLs, any order"
    )
    p_sp.add_argument(
        "-o",
        "--output",
        default="cloned_repos",
        help="Output directory (default: cloned_repos)",
    )
    p_sp.add_argument(
        "-w", "--workers", type=int, default=4, help="Parallel workers (default: 4)"
    )
    p_sp.set_defaults(func=cmd_sparse)

    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
