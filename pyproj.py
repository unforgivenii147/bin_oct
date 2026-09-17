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
    project_dir = Path.cwd() / pkg
    project_dir.mkdir(exist_ok=True)
    cwd = project_dir
    version = "1.4.7"
    readme_path = cwd / "README.md"
    write_file_if_missing(readme_path, f"# {pkg}\n")
    src_pkg = cwd / "src" / pkg
    src_pkg.mkdir(parents=True, exist_ok=True)
    write_file_if_missing(src_pkg / "__init__.py")
    if simple_cli:
        main_py = src_pkg / "__main__.py"
        write_file_if_missing(
            main_py,
            """def main() -> None:
    \"\"\"CLI entry point.\"\"\"
    print("Hello from ", __package__)
if __name__ == "__main__":
    raise SystemExit(main())
""",
        )
    tests_path = cwd / "tests"
    tests_path.mkdir(exist_ok=True)
    write_file_if_missing(tests_path / "__init__.py")
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
            "package_dir =",
            "    = src",
            "packages = find:",
            "python_requires = >=3.11",
            "",
            "[options.packages.find]",
            "where = src",
        ]
    )
    if simple_cli:
        cfg_content.extend(
            [
                "",
                "[options.entry_points]",
                "console_scripts =",
                f"    {pkg} = {pkg}.__main__:main",
            ]
        )
    setup_cfg.write_text("\n".join(cfg_content))
    print(f"Project '{pkg}' initialized in {cwd}")


def main():
    parser = argparse.ArgumentParser(
        description="Initialize a new Python project structure"
    )
    parser.add_argument("package_name", help="Name of the package to create")
    parser.add_argument("--author", help="Author name (overrides ~/.myinfo if set)")
    parser.add_argument("--email", help="Author email (overrides ~/.myinfo if set)")
    parser.add_argument("--url", help="Project URL (overrides ~/.myinfo if set)")
    parser.add_argument(
        "--cli", action="store_true", help="Create a simple CLI entry point"
    )
    parser.add_argument(
        "--version", default="1.4.7", help="Initial version (default: 1.4.7)"
    )
    args = parser.parse_args()
    user_info = load_user_info()
    author = args.author or user_info.get("author", "")
    email = args.email or user_info.get("email", "")
    url = args.url or user_info.get("url", "")
    create_project_structure(
        pkg=args.package_name,
        author=author,
        email=email,
        url=url,
        simple_cli=args.cli,
    )


if __name__ == "__main__":
    main()
