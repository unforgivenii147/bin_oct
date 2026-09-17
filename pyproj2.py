#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
from pathlib import Path


def load_user_info() -> dict[str, str]:
    info_path = Path.home() / ".myinfo"
    info = {}
    if not info_path.exists():
        return info
    for line in info_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        info[key.strip()] = val.strip()
    return info


def write_file_if_missing(path: Path, content: str = "") -> None:
    if not path.exists():
        path.write_text(content)


def create_project_structure(
    pkg: str, author: str, email: str, url: str, simple_cli: bool = False
) -> None:
    cwd = Path.cwd()
    version = "1.4.7"
    readme_path = cwd / "README.md"
    write_file_if_missing(readme_path, f"# {pkg}\n")
    setup_py = cwd / "setup.py"
    setup_py.write_text('__import__("setuptools").setup()\n')
    setup_cfg = cwd / "setup.cfg"
    cfg_content = ["[metadata]", f"name = {pkg}", f"version = {version}"]
    if author:
        cfg_content.append(f"author = {author}")
    if email:
        cfg_content.append(f"author_email = {email}")
    if url:
        cfg_content.append(f"url = {url}")
    cfg_content.extend(
        [
            "",
            "[options]",
            f"py_modules = {pkg}",
            "python_requires = >=3.11",
            "[options.entry_points]",
            "console_scripts =",
            f"{pkg} = {pkg}:main",
            "",
        ]
    )
    setup_cfg.write_text("\n".join(cfg_content))
    pyproject_path = cwd / "pyproject.toml"
    pyproject_path.write_text(f"""
[build-system]
requires = ["setuptools>=69.0", "wheel-"]
build-backend = "setuptools.build_meta"
[project.scripts]
{pkg} = "{pkg}:main"
""")
    print(f"Project '{pkg}' initialized in {cwd}")


def main() -> None:
    user_info = load_user_info()
    parser = argparse.ArgumentParser(
        description="Initialize a Python project structure"
    )
    parser.add_argument("name", help="Package name")
    parser.add_argument(
        "--version", default="1.4.7", help="Initial version (default: 1.4.7)"
    )
    parser.add_argument(
        "-s",
        "--simple-cli",
        action="store_true",
        help="Create with simple CLI entry point",
    )
    args = parser.parse_args()
    author = user_info.get("name", "")
    email = user_info.get("email", "")
    github_user = user_info.get("github_username", "")
    url = f"https://github.com/{github_user}/{args.name}" if github_user else ""
    create_project_structure(args.name, author, email, url, args.simple_cli)


if __name__ == "__main__":
    raise SystemExit(main())
