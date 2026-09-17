#!/data/data/com.termux/files/home/.local/bin/python
"""
Report files added in every commit of a git repo as JSON.
Uses dulwich (pure Python git implementation) - no subprocess.
"""

import json
import sys

from dulwich.repo import Repo


def get_added_files_per_commit(repo_path: str) -> dict:
    """
    Walk the commit history and collect files that were *added*
    (i.e., not present in any parent) in each commit.

    Returns a dict: {short_hash (8 chars): [list of filenames]}
    """
    repo = Repo(repo_path)
    result = {}

    try:
        walker = repo.get_walker()
        commits = list(walker)

        tree_files_cache = {}

        def tree_files(tree_sha):
            if tree_sha in tree_files_cache:
                return tree_files_cache[tree_sha]
            files = set()
            tree = repo[tree_sha]
            stack = [("", tree)]
            while stack:
                prefix, t = stack.pop()
                for item in t.iteritems():
                    name = (
                        item.path.decode()
                        if isinstance(item.path, bytes)
                        else item.path
                    )
                    full = f"{prefix}{name}"
                    if item.mode & 0o170000 == 0o040000:  # directory
                        stack.append((full + "/", repo[item.sha]))
                    else:
                        files.add(full)
            tree_files_cache[tree_sha] = files
            return files

        for entry in commits:
            commit = entry.commit
            commit_sha = commit.id.decode()
            short = commit_sha[:8]

            current_files = tree_files(commit.tree)

            parent_files = set()
            for parent_sha in commit.parents:
                parent = repo[parent_sha]
                parent_files |= tree_files(parent.tree)

            added = current_files - parent_files
            added_names = sorted({f.split("/")[-1] for f in added})

            result[short] = added_names

    finally:
        repo.close()

    return result


def main():
    repo_path = sys.argv[1] if len(sys.argv) > 1 else "."
    output_path = sys.argv[2] if len(sys.argv) > 2 else "added_files.json"

    data = get_added_files_per_commit(repo_path)

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Wrote {len(data)} commits to {output_path}")


if __name__ == "__main__":
    main()
