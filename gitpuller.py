#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

from git import GitCommandError, Repo


def find_git_repos(root_path: Path) -> list[Path]:
    git_repos = []
    for item in root_path.iterdir():
        if not item.is_dir():
            continue
        if (item / ".git").exists():
            git_repos.append(item)
        else:
            git_repos.extend(find_git_repos(item))
    return git_repos


def git_pull_all() -> None:
    cwd = Path.cwd()
    print(f"🔍 Scanning for git repositories in: {cwd}")
    repos = find_git_repos(cwd)
    if not repos:
        print("No git repositories found")
        return
    print(f"Found {len(repos)} git repository(ies)\n")
    pulled_repos = []
    failed_repos = []
    for repo_path in repos:
        print(f"📁 Repository: {repo_path.relative_to(cwd)}")
        try:
            repo = Repo(repo_path)
            current_branch = repo.active_branch.name
            print(f"   Branch: {current_branch}")
            if not repo.remotes:
                failed_repos.append((repo_path, "No remote configured"))
                print("   ❌ No remote configured")
                continue
            remote_name = repo.remotes[0].name
            pull_result = repo.remotes[remote_name].pull()
            success = False
            for info in pull_result:
                if hasattr(info, "flags"):
                    if info.flags & info.ERROR:
                        failed_repos.append((repo_path, str(info.note)))
                        print(f"   ❌ Failed: {info.note}")
                    else:
                        success = True
                        if hasattr(info, "commit") and info.commit:
                            print(f"   ✅ Pulled successfully: {info.commit}")
                        else:
                            print("   ℹ️  Already up to date")
                else:
                    success = True
                    print("   ✅ Pull completed")
            if success:
                pulled_repos.append(repo_path)
        except GitCommandError as e:
            failed_repos.append((repo_path, str(e)))
            print(f"   ❌ Git error: {e}")
        except Exception as e:
            failed_repos.append((repo_path, f"Unexpected error: {e!s}"))
            print(f"   ❌ Error: {e}")
    print("\n" + "=" * 40)
    print("SUMMARY")
    print("-" * 40)
    if pulled_repos:
        print(f"\n✅ Successfully pulled ({len(pulled_repos)} repos):")
        for repo_path in pulled_repos:
            print(f"   - {repo_path.relative_to(cwd)}")
    if failed_repos:
        print(f"\n❌ Failed ({len(failed_repos)} repos):")
        for repo_path, error in failed_repos:
            print(f"   - {repo_path.relative_to(cwd)}: {error}")


if __name__ == "__main__":
    try:
        git_pull_all()
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
