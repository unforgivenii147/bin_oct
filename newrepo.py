#!/data/data/com.termux/files/home/.local/bin/python
import argparse
import os
import subprocess
import sys
from typing import Tuple, Optional, List
from abc import ABC, abstractmethod


class GitBackend(ABC):
    @abstractmethod
    def run_command(self, cmd, check=True):
        pass

    @abstractmethod
    def is_git_repo(self) -> bool:
        pass

    @abstractmethod
    def get_dir_name(self) -> str:
        pass

    @abstractmethod
    def init_repo(self):
        pass

    @abstractmethod
    def get_remote_url(self) -> Optional[str]:
        pass

    @abstractmethod
    def create_remote_repo(self, repo_name: str):
        pass

    @abstractmethod
    def fetch_origin(self) -> bool:
        pass

    @abstractmethod
    def add_all_files(self):
        pass

    @abstractmethod
    def has_changes(self) -> bool:
        pass

    @abstractmethod
    def commit(self, message: str):
        pass

    @abstractmethod
    def get_current_branch(self) -> str:
        pass

    @abstractmethod
    def push_upstream(self, branch: str) -> Tuple[bool, Optional[str]]:
        pass

    @abstractmethod
    def pull_rebase(self, branch: str):
        pass


class SubprocessBackend(GitBackend):
    def run_command(self, cmd, check=True):
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            print(f"Error: {result.stderr}")
            sys.exit(1)
        return result

    def is_git_repo(self) -> bool:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"], capture_output=True, text=True
        )
        return result.returncode == 0

    def get_dir_name(self) -> str:
        return os.path.basename(os.getcwd())

    def init_repo(self):
        self.run_command(["git", "init"])

    def get_remote_url(self) -> Optional[str]:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"], capture_output=True, text=True
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def create_remote_repo(self, repo_name: str):
        self.run_command(["gh", "repo", "create", repo_name, "--public", "--source=."])

    def fetch_origin(self) -> bool:
        result = subprocess.run(
            ["git", "fetch", "origin"], capture_output=True, text=True
        )
        return result.returncode == 0

    def add_all_files(self):
        self.run_command(["git", "add", "-A"])

    def has_changes(self) -> bool:
        status = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True
        )
        return bool(status.stdout.strip())

    def commit(self, message: str):
        self.run_command(["git", "commit", "-m", message])

    def get_current_branch(self) -> str:
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True
        )
        return branch_result.stdout.strip() if branch_result.returncode == 0 else "main"

    def push_upstream(self, branch: str) -> Tuple[bool, Optional[str]]:
        push_result = subprocess.run(
            ["git", "push", "--set-upstream", "origin", branch],
            capture_output=True,
            text=True,
        )
        if push_result.returncode == 0:
            return True, None
        return False, push_result.stderr

    def pull_rebase(self, branch: str):
        self.run_command(["git", "pull", "origin", branch, "--rebase"])


class GitpythonBackend(GitBackend):
    def __init__(self):
        try:
            import git

            self.git = git
        except ImportError:
            raise ImportError("GitPython not installed")
        self.repo = None

    def run_command(self, cmd, check=True):
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            print(f"Error: {result.stderr}")
            sys.exit(1)
        return result

    def is_git_repo(self) -> bool:
        try:
            self.repo = self.git.Repo(".")
            return True
        except self.git.InvalidGitRepositoryError:
            return False

    def get_dir_name(self) -> str:
        return os.path.basename(os.getcwd())

    def init_repo(self):
        self.repo = self.git.Repo.init(".")

    def get_remote_url(self) -> Optional[str]:
        try:
            return self.repo.remote("origin").url
        except (ValueError, AttributeError):
            return None

    def create_remote_repo(self, repo_name: str):
        self.run_command(["gh", "repo", "create", repo_name, "--public", "--source=."])
        remote_url = self.run_command(
            ["gh", "repo", "view", "--json", "url", "-q", ".url"],
            check=False,
        ).stdout.strip()
        if not self.get_remote_url():
            self.repo.create_remote("origin", remote_url)

    def fetch_origin(self) -> bool:
        try:
            self.repo.remotes.origin.fetch()
            return True
        except Exception:
            return False

    def add_all_files(self):
        self.repo.index.add(["."])

    def has_changes(self) -> bool:
        return bool(self.repo.index.diff("HEAD")) or bool(self.repo.untracked_files)

    def commit(self, message: str):
        self.repo.index.commit(message)

    def get_current_branch(self) -> str:
        try:
            return self.repo.active_branch.name
        except TypeError:
            return "main"

    def push_upstream(self, branch: str) -> Tuple[bool, Optional[str]]:
        try:
            self.repo.remotes.origin.push(branch)
            return True, None
        except Exception as e:
            return False, str(e)

    def pull_rebase(self, branch: str):
        self.run_command(["git", "pull", "origin", branch, "--rebase"])


class LibGit2Backend(GitBackend):
    def __init__(self):
        try:
            import pygit2

            self.pygit2 = pygit2
        except ImportError:
            raise ImportError("pygit2 not installed")
        self.repo = None

    def run_command(self, cmd, check=True):
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            print(f"Error: {result.stderr}")
            sys.exit(1)
        return result

    def is_git_repo(self) -> bool:
        try:
            self.repo = self.pygit2.Repository(".")
            return True
        except KeyError:
            return False

    def get_dir_name(self) -> str:
        return os.path.basename(os.getcwd())

    def init_repo(self):
        self.repo = self.pygit2.init_repository(".")

    def get_remote_url(self) -> Optional[str]:
        try:
            return self.repo.remotes["origin"].url
        except KeyError:
            return None

    def create_remote_repo(self, repo_name: str):
        self.run_command(["gh", "repo", "create", repo_name, "--public", "--source=."])

    def fetch_origin(self) -> bool:
        try:
            self.repo.remotes["origin"].fetch()
            return True
        except Exception:
            return False

    def add_all_files(self):
        self.repo.index.add_all()
        self.repo.index.write()

    def has_changes(self) -> bool:
        self.repo.index.read()
        return bool(self.repo.status_file_flags())

    def commit(self, message: str):
        self.repo.index.write()
        tree = self.repo.index.write_tree()
        author = self.pygit2.Signature("User", "user@example.com")
        self.repo.create_commit(
            "HEAD", author, author, message, tree, [self.repo.head.target]
        )

    def get_current_branch(self) -> str:
        try:
            return self.repo.active_branch.shorthand
        except Exception:
            return "main"

    def push_upstream(self, branch: str) -> Tuple[bool, Optional[str]]:
        try:
            self.repo.remotes["origin"].push(
                [f"refs/heads/{branch}:refs/heads/{branch}"]
            )
            return True, None
        except Exception as e:
            return False, str(e)

    def pull_rebase(self, branch: str):
        self.run_command(["git", "pull", "origin", branch, "--rebase"])


class DulwichBackend(GitBackend):
    def __init__(self):
        try:
            import dulwich.repo

            self.dulwich = dulwich
        except ImportError:
            raise ImportError("dulwich not installed")
        self.repo = None

    def run_command(self, cmd, check=True):
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            print(f"Error: {result.stderr}")
            sys.exit(1)
        return result

    def is_git_repo(self) -> bool:
        try:
            self.repo = self.dulwich.repo.Repo(".")
            return True
        except self.dulwich.repo.NotGitRepository:
            return False

    def get_dir_name(self) -> str:
        return os.path.basename(os.getcwd())

    def init_repo(self):
        self.repo = self.dulwich.repo.Repo.init(".")

    def get_remote_url(self) -> Optional[str]:
        try:
            config = self.repo.get_config()
            return config.get((b"remote", b"origin"), b"url").decode()
        except Exception:
            return None

    def create_remote_repo(self, repo_name: str):
        self.run_command(["gh", "repo", "create", repo_name, "--public", "--source=."])

    def fetch_origin(self) -> bool:
        try:
            self.repo.fetch("origin")
            return True
        except Exception:
            return False

    def add_all_files(self):
        self.run_command(["git", "add", "-A"])

    def has_changes(self) -> bool:
        self.run_command(["git", "status", "--porcelain"], check=False)
        status = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True
        )
        return bool(status.stdout.strip())

    def commit(self, message: str):
        self.run_command(["git", "commit", "-m", message])

    def get_current_branch(self) -> str:
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True
        )
        return branch_result.stdout.strip() if branch_result.returncode == 0 else "main"

    def push_upstream(self, branch: str) -> Tuple[bool, Optional[str]]:
        push_result = subprocess.run(
            ["git", "push", "--set-upstream", "origin", branch],
            capture_output=True,
            text=True,
        )
        if push_result.returncode == 0:
            return True, None
        return False, push_result.stderr

    def pull_rebase(self, branch: str):
        self.run_command(["git", "pull", "origin", branch, "--rebase"])


class PyGithubBackend(GitBackend):
    def __init__(self):
        try:
            from github import Github

            self.Github = Github
        except ImportError:
            raise ImportError("PyGithub not installed")
        self.repo = None

    def run_command(self, cmd, check=True):
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            print(f"Error: {result.stderr}")
            sys.exit(1)
        return result

    def is_git_repo(self) -> bool:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"], capture_output=True, text=True
        )
        return result.returncode == 0

    def get_dir_name(self) -> str:
        return os.path.basename(os.getcwd())

    def init_repo(self):
        self.run_command(["git", "init"])

    def get_remote_url(self) -> Optional[str]:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"], capture_output=True, text=True
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def create_remote_repo(self, repo_name: str):
        self.run_command(["gh", "repo", "create", repo_name, "--public", "--source=."])

    def fetch_origin(self) -> bool:
        result = subprocess.run(
            ["git", "fetch", "origin"], capture_output=True, text=True
        )
        return result.returncode == 0

    def add_all_files(self):
        self.run_command(["git", "add", "-A"])

    def has_changes(self) -> bool:
        status = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True
        )
        return bool(status.stdout.strip())

    def commit(self, message: str):
        self.run_command(["git", "commit", "-m", message])

    def get_current_branch(self) -> str:
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True
        )
        return branch_result.stdout.strip() if branch_result.returncode == 0 else "main"

    def push_upstream(self, branch: str) -> Tuple[bool, Optional[str]]:
        push_result = subprocess.run(
            ["git", "push", "--set-upstream", "origin", branch],
            capture_output=True,
            text=True,
        )
        if push_result.returncode == 0:
            return True, None
        return False, push_result.stderr

    def pull_rebase(self, branch: str):
        self.run_command(["git", "pull", "origin", branch, "--rebase"])


class TyperBackend(GitBackend):
    def __init__(self):
        try:
            import typer

            self.typer = typer
        except ImportError:
            raise ImportError("typer not installed")

    def run_command(self, cmd, check=True):
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            print(f"Error: {result.stderr}")
            sys.exit(1)
        return result

    def is_git_repo(self) -> bool:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"], capture_output=True, text=True
        )
        return result.returncode == 0

    def get_dir_name(self) -> str:
        return os.path.basename(os.getcwd())

    def init_repo(self):
        self.run_command(["git", "init"])

    def get_remote_url(self) -> Optional[str]:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"], capture_output=True, text=True
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def create_remote_repo(self, repo_name: str):
        self.run_command(["gh", "repo", "create", repo_name, "--public", "--source=."])

    def fetch_origin(self) -> bool:
        result = subprocess.run(
            ["git", "fetch", "origin"], capture_output=True, text=True
        )
        return result.returncode == 0

    def add_all_files(self):
        self.run_command(["git", "add", "-A"])

    def has_changes(self) -> bool:
        status = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True
        )
        return bool(status.stdout.strip())

    def commit(self, message: str):
        self.run_command(["git", "commit", "-m", message])

    def get_current_branch(self) -> str:
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True
        )
        return branch_result.stdout.strip() if branch_result.returncode == 0 else "main"

    def push_upstream(self, branch: str) -> Tuple[bool, Optional[str]]:
        push_result = subprocess.run(
            ["git", "push", "--set-upstream", "origin", branch],
            capture_output=True,
            text=True,
        )
        if push_result.returncode == 0:
            return True, None
        return False, push_result.stderr

    def pull_rebase(self, branch: str):
        self.run_command(["git", "pull", "origin", branch, "--rebase"])


class GhBackend(GitBackend):
    def __init__(self):
        try:
            import subprocess as sp

            self.sp = sp
        except ImportError:
            raise ImportError("gh cli not installed")

    def run_command(self, cmd, check=True):
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            print(f"Error: {result.stderr}")
            sys.exit(1)
        return result

    def is_git_repo(self) -> bool:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"], capture_output=True, text=True
        )
        return result.returncode == 0

    def get_dir_name(self) -> str:
        return os.path.basename(os.getcwd())

    def init_repo(self):
        self.run_command(["git", "init"])

    def get_remote_url(self) -> Optional[str]:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"], capture_output=True, text=True
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def create_remote_repo(self, repo_name: str):
        self.run_command(["gh", "repo", "create", repo_name, "--public", "--source=."])

    def fetch_origin(self) -> bool:
        result = subprocess.run(
            ["git", "fetch", "origin"], capture_output=True, text=True
        )
        return result.returncode == 0

    def add_all_files(self):
        self.run_command(["git", "add", "-A"])

    def has_changes(self) -> bool:
        status = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True
        )
        return bool(status.stdout.strip())

    def commit(self, message: str):
        self.run_command(["git", "commit", "-m", message])

    def get_current_branch(self) -> str:
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True
        )
        return branch_result.stdout.strip() if branch_result.returncode == 0 else "main"

    def push_upstream(self, branch: str) -> Tuple[bool, Optional[str]]:
        push_result = subprocess.run(
            ["git", "push", "--set-upstream", "origin", branch],
            capture_output=True,
            text=True,
        )
        if push_result.returncode == 0:
            return True, None
        return False, push_result.stderr

    def pull_rebase(self, branch: str):
        self.run_command(["git", "pull", "origin", branch, "--rebase"])


def is_transient_error(error_message: str) -> bool:
    transient_errors = [
        "RPC failed",
        "curl",
        "HTTP2 framing",
        "send-pack",
        "disconnect",
        "hung up",
        "Connection reset",
        "Connection refused",
        "timeout",
        "temporarily unavailable",
        "try again",
    ]
    return any(err.lower() in error_message.lower() for err in transient_errors)


def get_backend(backend_name: str) -> GitBackend:
    backends = {
        "subprocess": SubprocessBackend,
        "gitpython": GitpythonBackend,
        "pygithub": PyGithubBackend,
        "typer": TyperBackend,
        "libgit2": LibGit2Backend,
        "dulwich": DulwichBackend,
        "gh": GhBackend,
    }

    if backend_name not in backends:
        print(
            f"Unknown backend: {backend_name}. Available: {', '.join(backends.keys())}"
        )
        sys.exit(1)

    try:
        return backends[backend_name]()
    except ImportError as e:
        print(f"Backend {backend_name} not available: {e}")
        print(f"Falling back to subprocess backend")
        return SubprocessBackend()


def get_available_backends(preferred_backend: str) -> List[str]:
    all_backends = [
        "subprocess",
        "gitpython",
        "pygithub",
        "typer",
        "libgit2",
        "dulwich",
        "gh",
    ]

    if preferred_backend in all_backends:
        all_backends.remove(preferred_backend)
        all_backends.insert(0, preferred_backend)

    return all_backends


def main():
    parser = argparse.ArgumentParser(
        description="Git repository initialization and GitHub push"
    )
    parser.add_argument(
        "-b",
        "--backend",
        choices=[
            "subprocess",
            "gitpython",
            "pygithub",
            "typer",
            "libgit2",
            "dulwich",
            "gh",
        ],
        default="subprocess",
        help="Backend to use for git operations (default: subprocess)",
    )

    args = parser.parse_args()
    available_backends = get_available_backends(args.backend)

    backend = None
    for backend_name in available_backends:
        try:
            backend = get_backend(backend_name)
            print(f"Using backend: {backend_name}")
            break
        except ImportError:
            continue

    if backend is None:
        print("No available backends found")
        sys.exit(1)

    repo_name = backend.get_dir_name()
    print(f"Repository name: {repo_name}")

    if not backend.is_git_repo():
        print("Initializing git repository...")
        backend.init_repo()
    else:
        print("Git repository already initialized.")

    remote_url = backend.get_remote_url()
    if remote_url is None:
        print(f"Creating GitHub repository '{repo_name}'...")
        backend.create_remote_repo(repo_name)
    else:
        print("Remote 'origin' already exists. Checking if repo exists on GitHub...")
        if backend.fetch_origin():
            print("GitHub repository exists. Will push changes.")
        else:
            print(
                "Remote exists but seems inaccessible. You might need to authenticate."
            )
            print(f"Remote URL: {remote_url}")

    print("Adding all files...")
    backend.add_all_files()

    if backend.has_changes():
        print("Committing changes...")
        backend.commit("initial")
    else:
        print("No changes to commit.")

    print("Pushing to GitHub...")
    current_branch = backend.get_current_branch()
    success, error = backend.push_upstream(current_branch)

    if not success:
        if error and is_transient_error(error):
            print(f"Transient error detected: {error}")
            print("Attempting with alternative backends...")

            remaining_backends = [
                b
                for b in available_backends
                if b != type(backend).__name__.replace("Backend", "").lower()
            ]

            push_succeeded = False
            for alt_backend_name in remaining_backends:
                try:
                    alt_backend = get_backend(alt_backend_name)
                    print(f"\nRetrying with backend: {alt_backend_name}")
                    success, error = alt_backend.push_upstream(current_branch)
                    if success:
                        print(f"✅ Push succeeded with {alt_backend_name} backend")
                        push_succeeded = True
                        break
                    elif error and is_transient_error(error):
                        print(f"Transient error with {alt_backend_name}: {error}")
                        continue
                    else:
                        print(f"Failed with {alt_backend_name}: {error}")
                        continue
                except ImportError:
                    print(f"Backend {alt_backend_name} not available")
                    continue

            if not push_succeeded:
                print("All backends failed. Manual push required.")
                sys.exit(1)
        elif error and "remote contains work that you do not have" in error:
            print("Remote has changes. Pulling first...")
            backend.pull_rebase(current_branch)
            print("Pushing again...")
            success, error = backend.push_upstream(current_branch)
            if not success:
                print(f"Push still failed: {error}")
                sys.exit(1)
        else:
            print(f"Push failed: {error}")
            sys.exit(1)

    print(f"\n✅ Success! Repository '{repo_name}' is now on GitHub.")
    print(f"View it at: https://github.com/{repo_name}")


if __name__ == "__main__":
    raise SystemExit(main())
