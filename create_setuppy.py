#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate setup.py from pyproject.toml."
    )
    parser.add_argument(
        "project_dir",
        nargs="?",
        type=Path,
        default=Path("."),
        help="Project directory. Defaults to the current directory.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output setup.py path. Defaults to PROJECT_DIR/setup.py.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing setup.py.",
    )
    return parser.parse_args()


def read_pyproject(project_dir: Path) -> dict[str, Any]:
    path = project_dir / "pyproject.toml"
    if not path.is_file():
        raise FileNotFoundError(f"Missing pyproject.toml: {path}")
    with path.open("rb") as file:
        return tomllib.load(file)


def get_backend(data: dict[str, Any]) -> str:
    try:
        return data["build-system"]["build-backend"]
    except KeyError as error:
        raise ValueError(
            "pyproject.toml does not define [build-system].build-backend"
        ) from error


def dotted_to_path(name: str) -> str:
    return name.replace(".", "/").replace("-", "_")


def canonical_package_name(name: str) -> str:
    return re.sub(r"[-.]+", "_", name).lower()


def package_discovery_code(
    project_dir_name: str,
    package_name: str | None = None,
) -> str:
    if package_name:
        package_name_literal = repr(package_name)
        return f"""
from pathlib import Path
from setuptools import find_packages
_project_root = Path(__file__).parent
_package_name = {package_name_literal}
if (_project_root / _package_name).is_dir():
    packages = find_packages(
        where=str(_project_root),
        include=(_package_name, f"{{_package_name}}.*"),
    )
    package_dir = {{}}
elif (_project_root / "src" / _package_name).is_dir():
    packages = find_packages(
        where=str(_project_root / "src"),
        include=(_package_name, f"{{_package_name}}.*"),
    )
    package_dir = {{"": "src"}}
else:
    packages = []
    package_dir = {{}}
""".strip()
    return """
from pathlib import Path
from setuptools import find_packages
_project_root = Path(__file__).parent
if (_project_root / "src").is_dir():
    packages = find_packages(where=str(_project_root / "src"))
    package_dir = {"": "src"}
else:
    packages = find_packages(where=str(_project_root))
    package_dir = {}
""".strip()


def literal(value: Any) -> str:
    return repr(value)


def authors_to_setup(project: dict[str, Any]) -> dict[str, str]:
    authors = project.get("authors", [])
    names = [
        author["name"]
        for author in authors
        if isinstance(author, dict) and author.get("name")
    ]
    emails = [
        author["email"]
        for author in authors
        if isinstance(author, dict) and author.get("email")
    ]
    result: dict[str, str] = {}
    if names:
        result["author"] = ", ".join(names)
    if emails:
        result["author_email"] = ", ".join(emails)
    return result


def pep621_metadata(project: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "name": project["name"],
    }
    for key in (
        "version",
        "description",
        "readme",
        "license",
        "requires-python",
        "dependencies",
        "optional-dependencies",
        "classifiers",
        "keywords",
    ):
        if key in project:
            metadata[key] = project[key]
    metadata.update(authors_to_setup(project))
    urls = project.get("urls", {})
    if "Homepage" in urls:
        metadata["url"] = urls["Homepage"]
    scripts = project.get("scripts", {})
    if scripts:
        metadata["entry_points"] = {
            "console_scripts": [
                f"{name} = {target}" for name, target in scripts.items()
            ]
        }
    return metadata


def poetry_metadata(poetry: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "name": poetry["name"],
        "version": poetry["version"],
        "description": poetry.get("description", ""),
    }
    authors = poetry.get("authors", [])
    names: list[str] = []
    emails: list[str] = []
    for author in authors:
        match = re.match(r"^\s*(.*?)\s*<([^>]+)>\s*$", author)
        if match:
            names.append(match.group(1))
            emails.append(match.group(2))
        else:
            names.append(author)
    if names:
        metadata["author"] = ", ".join(names)
    if emails:
        metadata["author_email"] = ", ".join(emails)
    for poetry_key, setup_key in (
        ("homepage", "url"),
        ("classifiers", "classifiers"),
        ("keywords", "keywords"),
        ("readme", "long_description"),
        ("dependencies", "install_requires"),
    ):
        if poetry_key in poetry:
            metadata[setup_key] = poetry[poetry_key]
    scripts = poetry.get("scripts", {})
    if scripts:
        metadata["entry_points"] = {
            "console_scripts": [
                f"{name} = {target}" for name, target in scripts.items()
            ]
        }
    return metadata


def normalize_poetry_dependencies(
    dependencies: dict[str, Any],
) -> list[str]:
    requirements: list[str] = []
    for name, value in dependencies.items():
        if name == "python":
            continue
        if isinstance(value, str):
            if value == "*":
                requirements.append(name)
            else:
                requirements.append(f"{name}{value}")
            continue
        if isinstance(value, dict):
            version = value.get("version", "")
            extras = value.get("extras", [])
            requirement = name
            if extras:
                requirement += f"[{','.join(extras)}]"
            if version and version != "*":
                requirement += version
            requirements.append(requirement)
    return requirements


def setup_keyword_arguments(metadata: dict[str, Any]) -> str:
    lines: list[str] = []
    simple_mappings = {
        "name": "name",
        "version": "version",
        "description": "description",
        "author": "author",
        "author_email": "author_email",
        "url": "url",
        "classifiers": "classifiers",
        "keywords": "keywords",
        "install_requires": "install_requires",
        "python_requires": "python_requires",
        "long_description": "long_description",
    }
    for source_key, setup_key in simple_mappings.items():
        if source_key not in metadata:
            continue
        value = metadata[source_key]
        if source_key == "readme":
            continue
        if source_key == "requires-python":
            setup_key = "python_requires"
        if source_key == "dependencies":
            setup_key = "install_requires"
        if source_key == "optional-dependencies":
            continue
        lines.append(f"    {setup_key}={literal(value)},")
    if "entry_points" in metadata:
        lines.append(f"    entry_points={literal(metadata['entry_points'])},")
    optional = metadata.get("optional-dependencies", {})
    if optional:
        extras_require = {group: values for group, values in optional.items()}
        lines.append(f"    extras_require={literal(extras_require)},")
    return "\n".join(lines)


def generate_setup_py(
    data: dict[str, Any],
    project_dir: Path,
) -> str:
    backend = get_backend(data)
    project = data.get("project")
    poetry = data.get("tool", {}).get("poetry")
    if project is not None:
        metadata = pep621_metadata(project)
        package_name = project["name"]
    elif poetry is not None:
        metadata = poetry_metadata(poetry)
        if isinstance(poetry.get("dependencies"), dict):
            metadata["install_requires"] = normalize_poetry_dependencies(
                poetry["dependencies"]
            )
        package_name = canonical_package_name(poetry["name"])
    else:
        raise ValueError(
            "This script requires either [project] or [tool.poetry] metadata."
        )
    package_code = package_discovery_code(
        project_dir.name,
        package_name,
    )
    keyword_arguments = setup_keyword_arguments(metadata)
    backend_comment = f"# Original build backend: {backend}"
    return f'''\
"""Generated setup.py.
{backend_comment}
Generated by create_setup.py.
"""
from setuptools import setup
{package_code}
setup(
{keyword_arguments}
    packages=packages,
    package_dir=package_dir,
)
'''


def main() -> int:
    args = parse_args()
    project_dir = args.project_dir.expanduser().resolve()
    output_path = (
        args.output.expanduser().resolve()
        if args.output is not None
        else project_dir / "setup.py"
    )
    if output_path.exists() and not args.force:
        raise FileExistsError(
            f"{output_path} already exists; use --force to overwrite it"
        )
    data = read_pyproject(project_dir)
    generated = generate_setup_py(data, project_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(generated, encoding="utf-8")
    print(f"Created {output_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, FileExistsError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
