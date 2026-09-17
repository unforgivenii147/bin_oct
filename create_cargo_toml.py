#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from pathlib import Path


def parse_cargo_lock(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    version_match = re.search(r"^version\s*=\s*(\d+)", content, re.MULTILINE)
    lock_version = int(version_match.group(1)) if version_match else 3
    packages = []
    if lock_version >= 2:
        package_blocks = re.split(r"\n\[\[package\]\]\n", content)
        for block in package_blocks[1:]:
            pkg = parse_package_block(block)
            if pkg:
                packages.append(pkg)
    else:
        package_blocks = re.split(r"\n\[\[package\]\]\n", content)
        for block in package_blocks[1:]:
            pkg = parse_package_block_v1(block)
            if pkg:
                packages.append(pkg)
    return {"version": lock_version, "packages": packages}


def parse_package_block(block: str) -> dict | None:
    pkg = {}
    name_match = re.search(r'^name\s*=\s*"([^"]*)"', block, re.MULTILINE)
    version_match = re.search(r'^version\s*=\s*"([^"]*)"', block, re.MULTILINE)
    source_match = re.search(r'^source\s*=\s*"([^"]*)"', block, re.MULTILINE)
    if not name_match or not version_match:
        return None
    pkg["name"] = name_match.group(1)
    pkg["version"] = version_match.group(1)
    if source_match:
        pkg["source"] = source_match.group(1)
    dependencies = []
    dep_section = False
    for line in block.split("\n"):
        if line.strip().startswith("dependencies = ["):
            dep_section = True
            deps = re.findall(r'"([^"]*)"', line)
            dependencies.extend(deps)
            if "]" in line:
                dep_section = False
        elif dep_section:
            deps = re.findall(r'"([^"]*)"', line)
            dependencies.extend(deps)
            if "]" in line:
                dep_section = False
    if dependencies:
        pkg["dependencies"] = dependencies
    return pkg


def parse_package_block_v1(block: str) -> dict | None:
    pkg = {}
    name_match = re.search(r'^name\s*=\s*"([^"]*)"', block, re.MULTILINE)
    version_match = re.search(r'^version\s*=\s*"([^"]*)"', block, re.MULTILINE)
    if not name_match or not version_match:
        return None
    pkg["name"] = name_match.group(1)
    pkg["version"] = version_match.group(1)
    dependencies = []
    for line in block.split("\n"):
        dep_match = re.match(r'^\s*"([^"]+)\s+([^"]+)"', line)
        if dep_match:
            dependencies.append(f"{dep_match.group(1)} {dep_match.group(2)}")
    if dependencies:
        pkg["dependencies"] = dependencies
    return pkg


def generate_cargo_toml(
    packages: list[dict],
    root_package_name: str | None = None,
    root_version: str = "0.1.0",
    include_dev_deps: bool = False,
) -> str:
    lines = []
    lines.append("[package]")
    if root_package_name:
        lines.append(f'name = "{root_package_name}"')
    else:
        if packages:
            lines.append(f'name = "{packages[0]["name"]}"')
        else:
            lines.append('name = "generated-project"')
    lines.append(f'version = "{root_version}"')
    lines.append('edition = "2021"')
    lines.append("")
    if packages:
        lines.append("[dependencies]")
        root_deps = set()
        if packages and "dependencies" in packages[0]:
            root_deps.update(packages[0]["dependencies"])
        if root_deps:
            for dep_name in root_deps:
                dep_pkg = find_package(packages, dep_name)
                if dep_pkg:
                    lines.append(f'{dep_pkg["name"]} = "{dep_pkg["version"]}"')
                else:
                    lines.append(f'{dep_name} = "*"  # Version not found in lock file')
        else:
            for pkg in packages[1:]:
                lines.append(f'{pkg["name"]} = "{pkg["version"]}"')
    return "\n".join(lines)


def find_package(packages: list[dict], name: str) -> dict | None:
    for pkg in packages:
        if pkg["name"] == name:
            return pkg
    return None


def main():
    lock_file = "Cargo.lock"
    if len(sys.argv) > 1:
        lock_file = sys.argv[1]
    if not Path(lock_file).exists():
        print(f"Error: {lock_file} not found!")
        sys.exit(1)
    print(f"Parsing {lock_file}...")
    data = parse_cargo_lock(lock_file)
    if not data["packages"]:
        print("No packages found in lock file!")
        sys.exit(1)
    print(f"Found {len(data['packages'])} packages (lock file v{data['version']})")
    toml_content = generate_cargo_toml(
        data["packages"],
        root_package_name=None,
        root_version="0.1.0",
    )
    output_file = "Cargo.toml"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(toml_content)
    print(f"Generated {output_file}")
    print("\nPreview:")
    print("-" * 40)
    print(toml_content)


if __name__ == "__main__":
    raise SystemExit(main())
