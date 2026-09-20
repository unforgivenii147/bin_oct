#!/data/data/com.termux/files/home/.local/bin/python
"""
gh_repo.py — create a GitHub repository from a local project and push code.

Merged from 5 similar scripts. Original mapping
-----------------------------------------------
    mkghrepo.py    -> python gh_repo.py api        <repo_name> [description]
    new_repo.py    -> python gh_repo.py api-push   [-n NAME] [--branch main]
    new_repo2.py   -> python gh_repo.py gh-create  [-n NAME]
    newrepo.py     -> python gh_repo.py gh-cli     [-n NAME] [--branch main]
    pynewrepo.py   -> python gh_repo.py gh-managed [-n NAME] [-m MESSAGE]

Each subcommand corresponds to one original script and preserves its behavior.
Common logic (env-file parsing, GitHub REST creation, subprocess wrapper,
GitPython init) is factored into shared helpers.

Usage examples
--------------
  python gh_repo.py api my-new-project "my new repo"
  python gh_repo.py api-push -n my-new-project --branch main
  python gh_repo.py gh-create
  python gh_repo.py gh-cli
  python gh_repo.py gh-managed -n my-new-project -m "first commit"

Dependencies (any that are actually used by the chosen subcommand)
------------------------------------------------------------------
  requests, python-dotenv, GitPython, PyGithub (third-party)
  gh CLI, git (external tools)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence


# ---------------------------------------------------------------------------
# Defaults (previously hardcoded in the originals)
# ---------------------------------------------------------------------------

DEFAULT_GITHUB_USERNAME = "unforgivenii147"
DEFAULT_GIT_EMAIL = "adnanonagh@gmail.com"
DEFAULT_GIT_USER = "unforgivenii147"
DEFAULT_ENV_FILE = Path.home() / ".env"
DEFAULT_GLOBAL_GITIGNORE = Path.home() / ".gitignore"
DEFAULT_DESCRIPTION = "created with python"
DEFAULT_BRANCH = "main"
DEFAULT_API_PUSH_COMMIT_MESSAGE = "Update files"
DEFAULT_GH_CREATE_COMMIT_MESSAGE = "initial"
DEFAULT_GH_CLI_COMMIT_MESSAGE = "initial"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def parse_env_file(path: Path) -> dict[str, str]:
    """Read a KEY=VALUE env file. Missing file returns an empty dict."""
    env: dict[str, str] = {}
    try:
        with path.open() as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    except Exception as exc:
        print(f"Error reading {path}: {exc}")
    return env


def get_github_token(env_file: Path | None = None) -> str | None:
    """Return GITHUB_TOKEN from env-file or environment (env-file wins)."""
    env_file = env_file or DEFAULT_ENV_FILE
    env = parse_env_file(env_file)
    return env.get("GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")


def create_github_repo_via_api(
    token: str,
    name: str,
    description: str = "",
    private: bool = False,
    auto_init: bool = False,
    username: str | None = None,
) -> dict[str, Any] | None:
    """
    Create a repo using the GitHub REST API.

    Returns the JSON payload on success, or a synthesized dict containing
    ``ssh_url`` when the repo already exists (HTTP 422) and ``username`` was
    provided. Returns None on unrecoverable failure.
    """
    try:
        import requests
    except ImportError:
        print("Error: 'requests' is required. Install it with: pip install requests")
        return None

    url = "https://api.github.com/user/repos"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    payload = {
        "name": name,
        "description": description,
        "private": private,
        "auto_init": auto_init,
    }
    resp = requests.post(url, headers=headers, json=payload)

    if resp.status_code == 201:
        return resp.json()

    if resp.status_code == 422:
        print(f"Repository '{name}' may already exist on GitHub.")
        if username:
            return {"ssh_url": f"git@github.com:{username}/{name}.git"}

    try:
        message = resp.json().get("message", "Unknown error")
    except Exception:
        message = "Unknown error"
    print(f"Failed to create GitHub repo: {resp.status_code} — {message}")
    return None


def run_subprocess(
    cmd: Sequence[str],
    cwd: Path | None = None,
    check: bool = False,
    capture: bool = True,
) -> subprocess.CompletedProcess:
    """Thin wrapper around subprocess.run used by all subprocess-based modes."""
    return subprocess.run(
        list(cmd),
        cwd=str(cwd) if cwd else None,
        check=check,
        capture_output=capture,
        text=True,
    )


# ---------------------------------------------------------------------------
# Subcommand: api  (mkghrepo.py)
# ---------------------------------------------------------------------------

def cmd_api(args: argparse.Namespace) -> int:
    token = get_github_token(Path(args.env_file).expanduser())
    if not token:
        print("Error: GITHUB_TOKEN not found in ~/.env")
        print("Please add: GITHUB_TOKEN=your_github_token_here")
        return 1

    data = create_github_repo_via_api(
        token=token,
        name=args.repo_name,
        description=args.description,
        private=args.private,
        auto_init=True,
    )
    if data is None:
        return 1

    print("✅ Repository created successfully!")
    print(f"📁 Name: {data['name']}")
    print(f"🔗 URL: {data['html_url']}")
    print(f"📝 Clone URL: {data['clone_url']}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: api-push  (new_repo.py)
# ---------------------------------------------------------------------------

def cmd_api_push(args: argparse.Namespace) -> int:
    try:
        from git import Repo, InvalidGitRepositoryError
    except ImportError:
        print("Error: 'GitPython' is required. Install it with: pip install GitPython")
        return 1

    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None  # fall back to manual env parsing

    env_file = Path(args.env_file).expanduser()
    if load_dotenv is not None:
        load_dotenv(env_file)

    token = os.environ.get("GITHUB_TOKEN") or get_github_token(env_file)
    if not token:
        print("Error: GITHUB_TOKEN not found in environment variables.")
        return 1

    cwd = Path.cwd()
    repo_name = args.name or cwd.name
    branch = args.branch

    # 1. Ensure a local repo
    try:
        repo = Repo(cwd)
        print("Existing git repository found.")
    except InvalidGitRepositoryError:
        print("No git repository found. Creating new one...")
        repo = Repo.init(cwd)
        print("Git repository initialized.")

    # 2. Commit local changes if any
    if repo.is_dirty(untracked_files=True):
        repo.index.add(["*"])
        repo.index.commit(args.commit_message)
        print("Changes committed.")
    else:
        print("No changes to commit.")

    # 3. Ensure an 'origin' remote exists
    try:
        remote = repo.remote("origin")
        print(f"Remote 'origin' already exists: {remote.url}")
    except ValueError:
        print("No remote 'origin' found. Creating GitHub repository...")
        data = create_github_repo_via_api(
            token=token,
            name=repo_name,
            private=False,
            auto_init=False,
            username=args.github_username,
        )
        if data is None:
            return 1
        ssh_url = data.get("ssh_url") or f"git@github.com:{args.github_username}/{repo_name}.git"
        remote = repo.create_remote("origin", ssh_url)
        print(f"Remote 'origin' created: {ssh_url}")

    # 4. Push
    try:
        remote.push(refspec=f"{branch}:{branch}")
        print(f"Successfully pushed to {remote.url}")
    except Exception as exc:
        print(f"Push failed: {exc}")
        remote.push(refspec=f"{branch}:{branch}", set_upstream=True)

    print(f"✅ Repository '{repo_name}' is now on GitHub!")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: gh-create  (new_repo2.py)
# ---------------------------------------------------------------------------

def cmd_gh_create(args: argparse.Namespace) -> int:
    try:
        from git import Repo, InvalidGitRepositoryError, NoSuchPathError
    except ImportError:
        print("Error: 'GitPython' is required. Install it with: pip install GitPython")
        return 1

    try:
        from github import Github
        from github.Auth import Token
    except ImportError:
        print("Error: 'PyGithub' is required. Install it with: pip install PyGithub")
        return 1

    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None

    env_file = Path(args.env_file).expanduser()
    if load_dotenv is not None:
        load_dotenv(env_file)

    token = os.environ.get("GITHUB_TOKEN") or get_github_token(env_file)
    if not token:
        print("Set GITHUB_TOKEN in the environment.")
        return 1

    cwd = Path.cwd()
    repo_name = args.name or cwd.name
    username = args.github_username

    # 1. Copy global .gitignore if applicable
    global_gitignore = Path(args.global_gitignore).expanduser()
    local_gitignore = cwd / ".gitignore"
    if global_gitignore.exists() and not local_gitignore.exists():
        shutil.copy2(global_gitignore, local_gitignore)
        print(f"Copied {global_gitignore} -> {local_gitignore}")
    elif local_gitignore.exists():
        print(".gitignore already exists in current directory.")
    else:
        print(f"No global .gitignore found at {global_gitignore}")

    # 2. Ensure local git repo
    try:
        repo = Repo(cwd)
        print("Git repository already initialized.")
    except (InvalidGitRepositoryError, NoSuchPathError):
        print("Initializing git repository...")
        repo = Repo.init(cwd)

    # 3. Check if repo already exists on GitHub via PyGithub
    g = Github(auth=Token(token))
    try:
        user = g.get_user(username) if username else g.get_user()
        try:
            user.get_repo(repo_name)
            exists = True
        except Exception:
            exists = False
    finally:
        g.close()

    # 4. Ensure 'origin' remote
    if "origin" in [r.name for r in repo.remotes]:
        print("Remote 'origin' already exists.")
        return 0

    if exists:
        print(f"GitHub repo '{repo_name}' already exists on your account.")
        ssh_url = f"git@github.com:{username}/{repo_name}.git"
        repo.create_remote("origin", ssh_url)
        print(f"Added remote origin: {ssh_url}")
    else:
        print(f"GitHub repo '{repo_name}' does not exist yet.")
        gh_cmd = ["gh", "repo", "create", repo_name, "--public", "--source=."]
        print(f"Running: {' '.join(gh_cmd)}")
        result = run_subprocess(gh_cmd)
        if result.returncode != 0:
            print(f"Error: {result.stderr}")
            return 1
        ssh_url = f"git@github.com:{username}/{repo_name}.git"
        repo.create_remote("origin", ssh_url)
        print(f"Added remote origin: {ssh_url}")

    # 5. Stage & commit
    repo.git.add(all=True)
    if repo.is_dirty(untracked_files=True):
        print("Committing changes...")
        repo.index.commit(args.commit_message)
    else:
        print("No changes to commit.")

    # 6. Push, with a rebase-retry on non-fast-forward
    branch = repo.active_branch.name if not repo.head.is_detached else args.branch
    remote = repo.remote("origin")
    print(f"Pushing branch '{branch}'...")
    try:
        remote.push(refspec=f"{branch}:{branch}")
    except Exception as exc:
        msg = str(exc)
        if "non-fast-forward" in msg or "fetch first" in msg:
            print("Remote has changes. Pulling first...")
            remote.pull(branch, rebase=True)
            print("Pushing again...")
            remote.push(refspec=f"{branch}:{branch}")
        else:
            raise

    print(f"\n✅ Success! Repository '{repo_name}' is on GitHub or updated there.")
    print(f"View it at: https://github.com/{repo_name}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: gh-cli  (newrepo.py)
# ---------------------------------------------------------------------------

def cmd_gh_cli(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    repo_name = args.name or cwd.name

    # 1. Local git?
    probe = run_subprocess(["git", "rev-parse", "--git-dir"])
    is_git = probe.returncode == 0

    print(f"Repository name: {repo_name}")
    if not is_git:
        print("Initializing git repository...")
        run_subprocess(["git", "init"], check=True)
    else:
        print("Git repository already initialized.")

    # 2. Existing origin?
    origin = run_subprocess(["git", "remote", "get-url", "origin"])
    if origin.returncode != 0:
        print(f"Creating GitHub repository '{repo_name}'...")
        res = subprocess.run(
            ["gh", "repo", "create", repo_name, "--public", "--source=."],
        )
        if res.returncode != 0:
            return 1
    else:
        print("Remote 'origin' already exists. Checking if repo exists on GitHub...")
        fetch = run_subprocess(["git", "fetch", "origin"])
        if fetch.returncode == 0:
            print("GitHub repository exists. Will push changes.")
        else:
            print("Remote exists but seems inaccessible. You might need to authenticate.")
            print(f"Remote URL: {origin.stdout.strip()}")

    # 3. Stage & commit
    print("Adding all files...")
    run_subprocess(["git", "add", "-A"], check=True)
    status = run_subprocess(["git", "status", "--porcelain"])
    if status.stdout.strip():
        print("Committing changes...")
        run_subprocess(["git", "commit", "-m", args.commit_message], check=True)
    else:
        print("No changes to commit.")

    # 4. Push (with rebase-retry)
    print("Pushing to GitHub...")
    branch_probe = run_subprocess(["git", "branch", "--show-current"])
    current_branch = (
        branch_probe.stdout.strip() if branch_probe.returncode == 0 else args.branch
    )
    push = run_subprocess(
        ["git", "push", "--set-upstream", "origin", current_branch]
    )
    if push.returncode != 0:
        if "remote contains work that you do not have" in (push.stderr or ""):
            print("Remote has changes. Pulling first...")
            run_subprocess(
                ["git", "pull", "origin", current_branch, "--rebase"], check=True
            )
            print("Pushing again...")
            run_subprocess(
                ["git", "push", "--set-upstream", "origin", current_branch], check=True
            )
        else:
            print(f"Push failed: {push.stderr}")
            return 1

    print(f"\n✅ Success! Repository '{repo_name}' is now on GitHub.")
    print(f"View it at: https://github.com/{repo_name}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: gh-managed  (pynewrepo.py)
# ---------------------------------------------------------------------------

class GitHubRepoManager:
    """Class-based gh CLI manager — port of pynewrepo.py's behavior."""

    def __init__(
        self,
        repo_name: str | None,
        github_username: str,
        git_email: str,
        git_user: str,
        branch: str,
    ) -> None:
        self.cwd: Path = Path.cwd()
        self.repo_name: str = repo_name or self.cwd.name
        self.github_username: str = github_username
        self.git_email: str = git_email
        self.git_user: str = git_user
        self.branch: str = branch
        self.repo_url: str = (
            f"https://github.com/{self.github_username}/{self.repo_name}.git"
        )

    # -- low-level -----------------------------------------------------------

    def _run(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        check: bool = False,
    ) -> tuple[int, str, str]:
        try:
            r = subprocess.run(
                list(cmd),
                check=check,
                cwd=str(cwd or self.cwd),
                text=True,
                capture_output=True,
            )
            return r.returncode, r.stdout.strip() if r.stdout else "", r.stderr.strip() if r.stderr else ""
        except Exception as exc:
            print(f"Error executing command: {' '.join(cmd)}")
            print(f"Exception: {exc}")
            return 1, "", str(exc)

    # -- environment checks --------------------------------------------------

    def _check_gh_cli_installed(self) -> bool:
        code, _, _ = self._run(["gh", "--version"])
        return code == 0

    def _check_gh_authenticated(self) -> bool:
        code, _, _ = self._run(["gh", "auth", "status"])
        return code == 0

    # -- local repo ----------------------------------------------------------

    def _repo_exists_locally(self) -> bool:
        return (self.cwd / ".git").exists()

    def _repo_exists_on_github(self) -> bool:
        code, _, _ = self._run(
            ["gh", "repo", "view", f"{self.github_username}/{self.repo_name}"]
        )
        return code == 0

    def _get_remote_url(self) -> str | None:
        code, out, _ = self._run(["git", "config", "--get", "remote.origin.url"])
        return out if code == 0 and out else None

    # -- actions -------------------------------------------------------------

    def _init_local_repo(self) -> None:
        print(f"\n📦 Initializing local git repository in {self.cwd}...")
        code, _, stderr = self._run(["git", "init"])
        if code != 0 and "Reinitialized" not in stderr and "Initialized" not in stderr:
            print(f"Error initializing git repo: {stderr}")
            sys.exit(1)
        self._run(["git", "config", "user.name", self.git_user])
        self._run(["git", "config", "user.email", self.git_email])
        print("✓ Local repository initialized")

    def _create_github_repo(self) -> bool:
        print(f"\n🌐 Creating repository on GitHub: {self.repo_name}...")
        if self._repo_exists_on_github():
            print(f"✓ Repository {self.repo_name} already exists on GitHub")
            return True
        code, out, err = self._run(
            [
                "gh",
                "repo",
                "create",
                self.repo_name,
                "--source=.",
                "--remote=origin",
                "--public",
            ]
        )
        if code != 0:
            print("Error creating repository on GitHub")
            print(f"stdout: {out}")
            print(f"stderr: {err}")
            return False
        print("✓ Repository created on GitHub")
        return True

    def _stage_all_changes(self) -> None:
        print("\n📝 Staging all changes...")
        code, _, err = self._run(["git", "add", "."])
        if code != 0:
            print(f"Error staging changes: {err}")
            sys.exit(1)
        print("✓ Changes staged")

    def _ensure_content(self) -> bool:
        visible = [f for f in self.cwd.glob("*") if f.name != ".git"]
        hidden = [f for f in self.cwd.glob(".*") if f.name not in {".git", ".", ".."}]
        has_content = bool(visible or hidden)
        if not has_content:
            print("📄 No files found, creating initial README.md...")
            readme = self.cwd / "README.md"
            if not readme.exists():
                readme.write_text(
                    f"# {self.repo_name}\n"
                    f"Repository initialized on {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                )
                print("✓ Created README.md")
                return True
        return has_content

    def _generate_commit_message(self) -> str:
        return datetime.now().strftime("Auto-commit: %Y-%m-%d %H:%M:%S")

    def _commit_changes(self, message: str | None = None) -> bool:
        message = message or self._generate_commit_message()
        print(f"\n💾 Committing changes with message: '{message}'")
        code, out, err = self._run(["git", "commit", "-m", message])
        if code != 0:
            if "nothing to commit" in err or "nothing to commit" in out:
                print("⚠️  Nothing to commit")
                return False
            print(f"Error committing changes: {err}")
            return False
        print("✓ Changes committed")
        return True

    def _add_remote(self) -> None:
        print(f"\n🔗 Adding remote: {self.repo_url}")
        code, current, _ = self._run(["git", "remote", "get-url", "origin"])
        if code == 0 and current:
            if current == self.repo_url:
                print("✓ Remote 'origin' already configured correctly")
                return
            print(f"Updating remote URL from {current} to {self.repo_url}")
            self._run(["git", "remote", "set-url", "origin", self.repo_url])
            return
        code, _, err = self._run(["git", "remote", "add", "origin", self.repo_url])
        if code != 0:
            print(f"Error adding remote: {err}")
            sys.exit(1)
        print("✓ Remote added")

    def _push_to_github(self, branch: str | None = None) -> None:
        branch = branch or self.branch
        print(f"\n🚀 Pushing to GitHub ({branch} branch)...")
        code, out, err = self._run(["git", "push", "-u", "origin", branch])
        if code != 0:
            print(f"stdout: {out}")
            print(f"stderr: {err}")
            if "permission denied" in err.lower():
                print("Error: Permission denied. Check your GitHub credentials.")
                sys.exit(1)
            elif "not found" in err.lower() or "does not appear" in err.lower():
                print(f"Note: Remote branch '{branch}' doesn't exist yet (creating on push)")
            else:
                print(f"Warning: Push encountered an issue: {err}")
        print("✓ Successfully pushed to GitHub")

    def _rename_branch_to_main(self) -> None:
        code, current, _ = self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if code == 0 and current and current != self.branch:
            print(f"\n🔄 Renaming branch from '{current}' to '{self.branch}'...")
            code, _, err = self._run(["git", "branch", "-M", self.branch])
            if code != 0:
                print(f"Warning: Could not rename branch: {err}")

    def handle_existing_repo(self) -> bool:
        print(f"\n⚠️  Git repository already exists in {self.cwd}")
        current = self._get_remote_url()
        print(f"Current remote: {current or 'None'}")
        while True:
            print("\nOptions:")
            print("1. Merge changes (stage and commit to current repo)")
            print("2. Create new repository (enter new name)")
            print("3. Exit")
            choice = input("\nSelect option (1-3): ").strip()
            if choice == "1":
                print("✓ Using existing repository")
                return True
            if choice == "2":
                new_name = input("Enter new repository name: ").strip()
                if not new_name:
                    print("Error: Repository name cannot be empty.")
                    continue
                self.repo_name = new_name
                self.repo_url = (
                    f"https://github.com/{self.github_username}/{self.repo_name}.git"
                )
                print(f"✓ New repository name set: {self.repo_name}")
                return False
            if choice == "3":
                print("Exiting...")
                sys.exit(0)
            print("Invalid choice. Please select 1, 2, or 3.")

    # -- orchestration -------------------------------------------------------

    def run(self, commit_message: str | None = None) -> int:
        print("-" * 40)
        print("GitHub Repository Manager (with gh CLI)")
        print("-" * 40)
        print(f"Directory: {self.cwd}")
        print(f"Repository: {self.repo_name}")
        print(f"GitHub User: {self.github_username}")
        print(f"Email: {self.git_email}")
        print("-" * 40)

        if not self._check_gh_cli_installed():
            print("\n❌ Error: GitHub CLI (gh) is not installed.")
            print("Please install it from: https://cli.github.com")
            return 1
        if not self._check_gh_authenticated():
            print("\n❌ Error: GitHub CLI is not authenticated.")
            print("Please run: gh auth login")
            return 1
        print("\n✓ GitHub CLI is installed and authenticated\n")

        if self._repo_exists_locally():
            keep = self.handle_existing_repo()
            if not keep:
                self._run(["git", "remote", "remove", "origin"])
        else:
            self._init_local_repo()

        self._ensure_content()
        self._stage_all_changes()

        if not self._commit_changes(commit_message):
            print("\n⚠️  Could not commit changes.")
            return 1

        self._rename_branch_to_main()

        if not self._create_github_repo():
            print("\n❌ Failed to create repository on GitHub")
            return 1

        self._add_remote()
        self._push_to_github()

        print("\n" + "=" * 40)
        print("✅ Success! Repository created and pushed to GitHub")
        print(f"Repository URL: https://github.com/{self.github_username}/{self.repo_name}")
        print("-" * 40)
        return 0


def cmd_gh_managed(args: argparse.Namespace) -> int:
    try:
        manager = GitHubRepoManager(
            repo_name=args.name,
            github_username=args.github_username,
            git_email=args.git_email,
            git_user=args.git_user,
            branch=args.branch,
        )
        return manager.run(commit_message=args.message)
    except KeyboardInterrupt:
        print("\n\nExiting...")
        return 0
    except Exception as exc:
        print(f"\nUnexpected error: {exc}")
        traceback.print_exc()
        return 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for all subcommands."""
    parser = argparse.ArgumentParser(
        prog="gh_repo.py",
        description="Create a GitHub repository from a local project and push code.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # api  (mkghrepo.py)
    p = sub.add_parser("api", help="Create a repo via GitHub REST API (mkghrepo.py).")
    p.add_argument("repo_name", help="Name of the new repository.")
    p.add_argument(
        "description",
        nargs="?",
        default=DEFAULT_DESCRIPTION,
        help=f"Repository description. Default: '{DEFAULT_DESCRIPTION}'.",
    )
    p.add_argument("--private", action="store_true", help="Make the repo private.")
    p.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help=f"Path to env file with GITHUB_TOKEN. Default: {DEFAULT_ENV_FILE}",
    )
    p.set_defaults(func=cmd_api)

    # api-push  (new_repo.py)
    p = sub.add_parser(
        "api-push",
        help="Init/commit local repo, create GitHub repo via API, push (new_repo.py).",
    )
    p.add_argument("-n", "--name", help="Repository name. Default: current directory name.")
    p.add_argument(
        "--branch",
        default=DEFAULT_BRANCH,
        help=f"Branch to push. Default: {DEFAULT_BRANCH}.",
    )
    p.add_argument(
        "--commit-message",
        default=DEFAULT_API_PUSH_COMMIT_MESSAGE,
        help=f"Commit message. Default: '{DEFAULT_API_PUSH_COMMIT_MESSAGE}'.",
    )
    p.add_argument(
        "--github-username",
        default=DEFAULT_GITHUB_USERNAME,
        help=f"GitHub username. Default: {DEFAULT_GITHUB_USERNAME}.",
    )
    p.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help=f"Path to env file with GITHUB_TOKEN. Default: {DEFAULT_ENV_FILE}",
    )
    p.set_defaults(func=cmd_api_push)

    # gh-create  (new_repo2.py)
    p = sub.add_parser(
        "gh-create",
        help="Copy .gitignore, init repo, use PyGithub + gh CLI to create and push (new_repo2.py).",
    )
    p.add_argument("-n", "--name", help="Repository name. Default: current directory name.")
    p.add_argument(
        "--github-username",
        default=DEFAULT_GITHUB_USERNAME,
        help=f"GitHub username. Default: {DEFAULT_GITHUB_USERNAME}.",
    )
    p.add_argument(
        "--global-gitignore",
        default=str(DEFAULT_GLOBAL_GITIGNORE),
        help=f"Path to global .gitignore. Default: {DEFAULT_GLOBAL_GITIGNORE}",
    )
    p.add_argument(
        "--commit-message",
        default=DEFAULT_GH_CREATE_COMMIT_MESSAGE,
        help=f"Commit message. Default: '{DEFAULT_GH_CREATE_COMMIT_MESSAGE}'.",
    )
    p.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help=f"Path to env file with GITHUB_TOKEN. Default: {DEFAULT_ENV_FILE}",
    )
    p.set_defaults(func=cmd_gh_create)

    # gh-cli  (newrepo.py)
    p = sub.add_parser(
        "gh-cli",
        help="Pure gh CLI + git subprocess workflow (newrepo.py).",
    )
    p.add_argument("-n", "--name", help="Repository name. Default: current directory name.")
    p.add_argument(
        "--branch",
        default=DEFAULT_BRANCH,
        help=f"Fallback branch. Default: {DEFAULT_BRANCH}.",
    )
    p.add_argument(
        "--commit-message",
        default=DEFAULT_GH_CLI_COMMIT_MESSAGE,
        help=f"Commit message. Default: '{DEFAULT_GH_CLI_COMMIT_MESSAGE}'.",
    )
    p.set_defaults(func=cmd_gh_cli)

    # gh-managed  (pynewrepo.py)
    p = sub.add_parser(
        "gh-managed",
        help="Class-based gh CLI manager with prompts & auto README (pynewrepo.py).",
    )
    p.add_argument("-n", "--name", help="Repository name. Default: current directory name.")
    p.add_argument(
        "-m",
        "--message",
        help="Custom commit message. Default: auto-generated with timestamp.",
    )
    p.add_argument(
        "--github-username",
        default=DEFAULT_GITHUB_USERNAME,
        help=f"GitHub username. Default: {DEFAULT_GITHUB_USERNAME}.",
    )
    p.add_argument(
        "--git-email",
        default=DEFAULT_GIT_EMAIL,
        help=f"Git user email. Default: {DEFAULT_GIT_EMAIL}.",
    )
    p.add_argument(
        "--git-user",
        default=DEFAULT_GIT_USER,
        help=f"Git user name. Default: {DEFAULT_GIT_USER}.",
    )
    p.add_argument(
        "--branch",
        default=DEFAULT_BRANCH,
        help=f"Main branch name. Default: {DEFAULT_BRANCH}.",
    )
    p.set_defaults(func=cmd_gh_managed)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
