#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys

from git import Repo


def sync_branch_with_upstream(repo_path: str = ".") -> bool:
    try:
        repo = Repo(repo_path)
        if repo.active_branch.name != "master":
            print(
                "Warning: Not on master branch. Current branch:",
                repo.active_branch.name,
            )
            response = input("Continue anyway? (y/n): ")
            if response.lower() != "y":
                return False
        print("Fetching from origin...")
        origin = repo.remotes.origin
        origin.fetch()
        upstream_branch = None
        if "origin/master" in repo.refs:
            upstream_branch = "origin/master"
        elif "origin/main" in repo.refs:
            upstream_branch = "origin/main"
        else:
            print("Error: Neither origin/master nor origin/main exists")
            return False
        print(f"Using upstream branch: {upstream_branch}")
        upstream_commit = repo.refs[upstream_branch].commit
        print("Rebasing with unrelated histories...")
        current_branch = repo.active_branch
        original_head = repo.head.commit
        try:
            repo.git.rebase(
                "--onto",
                upstream_commit,
                original_head,
                current_branch,
                allow_unrelated_histories=True,
            )
            print("Rebase successful")
        except Exception as e:
            print(f"Rebase failed: {e}")
            repo.git.rebase("--abort")
            return False
        print(f"Pushing to origin/{current_branch.name} with force-with-lease...")
        origin.push(
            refspec=f"{current_branch.name}:{current_branch.name}",
            force_with_lease=True,
        )
        print("Successfully synced branch!")
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False


def sync_with_plumbing(repo_path: str = ".") -> bool:
    try:
        repo = Repo(repo_path)
        origin = repo.remotes.origin
        origin.fetch()
        upstream_ref = None
        for ref in repo.refs:
            if ref.name in ["origin/master", "origin/main"]:
                upstream_ref = ref
                break
        if not upstream_ref:
            print("No origin/master or origin/main found")
            return False
        current_commit = repo.head.commit
        upstream_commit = upstream_ref.commit
        if current_commit != upstream_commit:
            print(
                f"Rebasing {current_commit.hexsha[:8]} onto {upstream_commit.hexsha[:8]}"
            )
            temp_branch = repo.create_head("temp_rebase", current_commit)
            temp_branch.checkout()
            try:
                repo.head.reset(upstream_commit, index=True, working_tree=True)
                repo.git.cherry_pick(
                    f"{current_commit.hexsha}..{upstream_commit.hexsha}"
                )
                repo.git.cherry_pick("--continue")
                repo.head.reference = repo.head.commit
            except Exception as e:
                print(f"Rebase failed: {e}")
                repo.git.rebase("--abort")
                return False
            finally:
                if temp_branch in repo.branches:
                    repo.delete_head(temp_branch)
        origin.push(refspec="master:master", force_with_lease=True)
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False


if __name__ == "__main__":
    success = sync_branch_with_upstream(".")
    sys.exit(0 if success else 1)
