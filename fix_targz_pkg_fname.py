#!/data/data/com.termux/files/home/.local/bin/python
import re
import tarfile
from pathlib import Path


def get_metadata_from_tar(tar_path):
    with tarfile.open(tar_path, "r:gz") as tar:
        members = tar.getmembers()
        if not members:
            return None, None
        top_dir = members[0].name.split("/")[0]
        for meta_name in ["PKG-INFO", "METADATA"]:
            try:
                member = tar.getmember(f"{top_dir}/{meta_name}")
                content = (
                    tar.extractfile(member).read().decode("utf-8", errors="ignore")
                )
                name = re.search(r"^Name:\s*(.+)$", content, re.MULTILINE)
                version = re.search(r"^Version:\s*(.+)$", content, re.MULTILINE)
                if name and version:
                    return name.group(1).strip(), version.group(1).strip()
            except KeyError:
                continue
        for fallback in ["setup.py", "setup.cfg", "pyproject.toml"]:
            try:
                member = tar.getmember(f"{top_dir}/{fallback}")
                content = (
                    tar.extractfile(member).read().decode("utf-8", errors="ignore")
                )
                name_match = re.search(r"name\s*=\s*['\"]([^'\"]+)['\"]", content)
                version_match = re.search(r"version\s*=\s*['\"]([^'\"]+)['\"]", content)
                if name_match:
                    name = name_match.group(1)
                if version_match:
                    version = version_match.group(1)
                if name and version:
                    return name, version
            except KeyError:
                continue
        match = re.match(r"^(.+)-(\d[^-]*)$", top_dir)
        if match:
            return match.group(1), match.group(2)
    return None, None


def rename_tar_files(directory):
    directory = Path(directory)
    tar_files = list(directory.glob("*.tar.gz"))
    for tar_path in tar_files:
        name, version = get_metadata_from_tar(tar_path)
        if name and version:
            new_name = f"{name}-{version}.tar.gz"
            new_path = directory / new_name
            if new_path != tar_path:
                if new_path.exists():
                    print(f"SKIP: {tar_path.name} -> {new_name} (already exists)")
                else:
                    tar_path.rename(new_path)
                    print(f"RENAMED: {tar_path.name} -> {new_name}")
        else:
            print(f"ERROR: Could not determine name/version for {tar_path.name}")


if __name__ == "__main__":
    import sys

    target_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    rename_tar_files(target_dir)
