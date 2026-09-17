#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
import sys
from collections import defaultdict


class TermuxDeborphan:
    def __init__(self):
        self.all_packages = set()
        self.dependencies = defaultdict(set)
        self.keep_list = set()

    def get_installed_packages(self) -> set[str]:
        try:
            result = subprocess.run(
                ["pkg", "list-installed"], capture_output=True, text=True
            )
            packages = set()
            for line in result.stdout.strip().split("\n"):
                if line:
                    pkg_name = line.split("/")[0]
                    packages.add(pkg_name)
            return packages
        except Exception as e:
            print(f"Error getting installed packages: {e}")
            sys.exit(1)

    def get_package_dependencies(self, package: str) -> set[str]:
        try:
            result = subprocess.run(
                ["pkg", "show", package], capture_output=True, text=True
            )
            dependencies = set()
            for line in result.stdout.split("\n"):
                if line.startswith("Depends:"):
                    deps_str = line.replace("Depends:", "").strip()
                    for dep in deps_str.split(","):
                        dep_name = dep.strip().split()[0]
                        if dep_name:
                            dependencies.add(dep_name)
                elif line.startswith("Pre-Depends:"):
                    deps_str = line.replace("Pre-Depends:", "").strip()
                    for dep in deps_str.split(","):
                        dep_name = dep.strip().split()[0]
                        if dep_name:
                            dependencies.add(dep_name)
            return dependencies
        except Exception:
            return set()

    def analyze(self) -> list[str]:
        print("Analyzing installed packages...")
        self.all_packages = self.get_installed_packages()
        print(f"Found {len(self.all_packages)} installed packages")
        print("Building dependency graph...")
        packages_with_dependents = set()
        for pkg in self.all_packages:
            deps = self.get_package_dependencies(pkg)
            for dep in deps:
                if dep in self.all_packages:
                    packages_with_dependents.add(dep)
                    self.dependencies[dep].add(pkg)
        orphans = []
        for pkg in self.all_packages:
            if pkg not in packages_with_dependents and pkg not in self.keep_list:
                orphans.append(pkg)
        return sorted(orphans)

    def load_keep_list(self, filename: str | None = None):
        if filename is None:
            filename = "/data/data/com.termux/files/home/.deborphan-keep"
        try:
            with open(filename, "r") as f:
                self.keep_list = {line.strip() for line in f if line.strip()}
            print(f"Loaded {len(self.keep_list)} packages to keep")
        except FileNotFoundError:
            self.keep_list = set()

    def save_keep_list(self, filename: str | None = None):
        if filename is None:
            filename = "/data/data/com.termux/files/home/.deborphan-keep"
        try:
            with open(filename, "w") as f:
                f.writelines(f"{pkg}\n" for pkg in sorted(self.keep_list))
            print(f"Saved keep list to {filename}")
        except Exception as e:
            print(f"Error saving keep list: {e}")

    def add_to_keep(self, package: str):
        self.keep_list.add(package)

    def remove_from_keep(self, package: str):
        self.keep_list.discard(package)


def interactive_mode():
    deborphan = TermuxDeborphan()
    deborphan.load_keep_list()
    orphans = deborphan.analyze()
    if not orphans:
        print("\n✓ No orphaned packages found!")
        return
    print(f"\n⚠ Found {len(orphans)} orphaned packages:\n")
    for i, pkg in enumerate(orphans, 1):
        print(f"{i}. {pkg}")
    print("\n--- Interactive Mode ---")
    print(
        "Commands: 'keep <pkg>' (add to keep list), 'remove <pkg>' (remove from keep list),"
    )
    print("          'list' (show keep list), 'save' (save keep list), 'quit' (exit)")
    print("-" * 40)
    while True:
        cmd = input("\n> ").strip()
        if cmd.startswith("keep "):
            pkg = cmd[5:].strip()
            if pkg in orphans:
                deborphan.add_to_keep(pkg)
                print(f"Added '{pkg}' to keep list")
            else:
                print(f"Package '{pkg}' not found in orphans")
        elif cmd.startswith("remove "):
            pkg = cmd[7:].strip()
            deborphan.remove_from_keep(pkg)
            print(f"Removed '{pkg}' from keep list")
        elif cmd == "list":
            if deborphan.keep_list:
                print("\nKeep list:")
                for pkg in sorted(deborphan.keep_list):
                    print(f"  - {pkg}")
            else:
                print("Keep list is empty")
        elif cmd == "save":
            deborphan.save_keep_list()
        elif cmd == "quit":
            print("Exiting...")
            break
        else:
            print("Unknown command")


def batch_mode(args):
    deborphan = TermuxDeborphan()
    deborphan.load_keep_list()
    orphans = deborphan.analyze()
    if not orphans:
        print("No orphaned packages found.")
        return 0
    for pkg in orphans:
        print(pkg)
    return len(orphans)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        interactive_mode()
    else:
        count = batch_mode(sys.argv[1:])
        print(f"\nTotal orphaned packages: {count}")
