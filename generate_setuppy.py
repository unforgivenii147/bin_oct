#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import configparser
import pprint
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkdn"}
PYTHON_SOURCE_SUFFIXES = {".py", ".pyi"}


@dataclass(frozen=True)
class ProjectFiles:
    root: Path
    pyproject: Path
    setup_py: Path
    setup_cfg: Path
    manifest: Path


def python_literal(value: Any) -> str:
    return pprint.pformat(
        value,
        indent=4,
        width=88,
        sort_dicts=False,
    )


def load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML in {path}: {exc}") from exc


def read_text_if_exists(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"Unable to read {path}: {exc}") from exc


def project_files(toml_path: Path) -> ProjectFiles:
    root = toml_path.parent
    return ProjectFiles(
        root=root,
        pyproject=toml_path,
        setup_py=root / "setup.py",
        setup_cfg=root / "setup.cfg",
        manifest=root / "MANIFEST.in",
    )


def extract_metadata(data: dict[str, Any]) -> dict[str, Any]:
    project = data.get("project", {})
    build_system = data.get("build-system", {})
    tool = data.get("tool", {})
    if not isinstance(project, dict):
        raise ValueError("[project] must be a TOML table")
    if not isinstance(tool, dict):
        tool = {}
    license_value = project.get("license", "")
    if isinstance(license_value, dict):
        license_value = license_value.get("text") or license_value.get("file", "")
    readme = project.get("readme", "")
    if isinstance(readme, dict):
        readme = dict(readme)
    return {
        "name": str(project.get("name", "")),
        "version": str(project.get("version", "0.0.0")),
        "description": str(project.get("description", "")),
        "readme": readme,
        "requires_python": str(project.get("requires-python", "")),
        "license": str(license_value),
        "authors": project.get("authors", []),
        "maintainers": project.get("maintainers", []),
        "keywords": project.get("keywords", []),
        "classifiers": project.get("classifiers", []),
        "urls": project.get("urls", {}),
        "scripts": project.get("scripts", {}),
        "gui_scripts": project.get("gui-scripts", {}),
        "entry_points": project.get("entry-points", {}),
        "dependencies": project.get("dependencies", []),
        "optional_dependencies": project.get("optional-dependencies", {}),
        "build_backend": build_system.get("build-backend", ""),
        "build_requires": build_system.get("requires", []),
        "tool": tool,
    }


def parse_setup_cfg(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(
        interpolation=None,
        delimiters=("=",),
    )
    if path.is_file():
        try:
            parser.read(path, encoding="utf-8")
        except configparser.Error as exc:
            raise ValueError(f"Invalid setup.cfg: {exc}") from exc
    return parser


def csv_values(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,\n]+", value) if item.strip()]


def parse_cfg_mapping(
    parser: configparser.ConfigParser,
    section: str,
) -> dict[str, Any]:
    if not parser.has_section(section):
        return {}
    result: dict[str, Any] = {}
    for key, value in parser.items(section):
        result[key] = csv_values(value)
    return result


def readme_expression(readme: Any) -> tuple[str, str]:
    if isinstance(readme, dict):
        readme_file = readme.get("file")
        content_type = readme.get("content-type", "text/markdown")
        if readme_file:
            return (
                f"read_text({readme_file!r})",
                repr(content_type),
            )
        return (
            repr(readme.get("text", "")),
            repr(content_type),
        )
    if isinstance(readme, str) and readme:
        suffix = Path(readme).suffix.lower()
        content_type = (
            "text/markdown"
            if suffix in MARKDOWN_SUFFIXES
            else "text/x-rst"
            if suffix == ".rst"
            else "text/plain"
        )
        return f"read_text({readme!r})", repr(content_type)
    return "''", repr("text/plain")


def author_values(people: Any) -> tuple[str, str]:
    names: list[str] = []
    emails: list[str] = []
    if not isinstance(people, list):
        return "", ""
    for person in people:
        if not isinstance(person, dict):
            continue
        name = str(person.get("name", "")).strip()
        email = str(person.get("email", "")).strip()
        if name:
            names.append(name)
        if email:
            emails.append(email)
    return ", ".join(names), ", ".join(emails)


def detect_extensions(metadata: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    setuptools_tool = metadata["tool"].get("setuptools", {})
    extensions = []
    if isinstance(setuptools_tool, dict):
        raw_extensions = setuptools_tool.get("ext-modules", [])
        if isinstance(raw_extensions, list):
            extensions = [
                ext
                for ext in raw_extensions
                if isinstance(ext, dict) and ext.get("name")
            ]
    if extensions:
        return extensions, "setuptools"
    backend = str(metadata.get("build_backend", "")).lower()
    requirements = " ".join(map(str, metadata.get("build_requires", []))).lower()
    if "scikit-build" in backend or "scikit-build" in requirements:
        return [], "scikit-build"
    if "mesonpy" in backend or "meson-python" in requirements:
        return [], "meson"
    if "cmake" in backend or "cmake" in requirements:
        return [], "cmake"
    return [], "none"


def build_package_arguments(
    metadata: dict[str, Any],
    cfg: configparser.ConfigParser,
) -> list[str]:
    arguments: list[str] = []
    package_find = parse_cfg_mapping(cfg, "options.packages.find")
    setuptools_tool = metadata["tool"].get("setuptools", {})
    if package_find:
        where = package_find.get("where", [""])[0]
        exclude = package_find.get("exclude", [])
        if where:
            arguments.append(f"package_dir={{'': {where!r}}}")
            find_call = f"find_packages(where={where!r}"
        else:
            find_call = "find_packages("
        if find_call.endswith("("):
            find_call += ")"
        else:
            find_call += ")"
        if exclude:
            find_call = (
                f"find_packages(where={where!r}, exclude={python_literal(exclude)})"
            )
        arguments.append(f"packages={find_call}")
    else:
        package_dir = (
            setuptools_tool.get("package-dir", {})
            if isinstance(setuptools_tool, dict)
            else {}
        )
        if package_dir:
            arguments.append(f"package_dir={python_literal(package_dir)}")
        arguments.append("packages=find_packages()")
    package_data = {}
    if isinstance(setuptools_tool, dict):
        package_data = setuptools_tool.get("package-data", {}) or {}
    if cfg.has_section("options.package_data"):
        package_data.update(parse_cfg_mapping(cfg, "options.package_data"))
    if package_data:
        arguments.append(f"package_data={python_literal(package_data)}")
    return arguments


def build_entry_points(metadata: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if metadata["scripts"]:
        result["console_scripts"] = [
            f"{name} = {target}" for name, target in metadata["scripts"].items()
        ]
    if metadata["gui_scripts"]:
        result["gui_scripts"] = [
            f"{name} = {target}" for name, target in metadata["gui_scripts"].items()
        ]
    for group, points in (metadata["entry_points"] or {}).items():
        if isinstance(points, dict):
            result[group] = [f"{name} = {target}" for name, target in points.items()]
        elif isinstance(points, list):
            result[group] = [str(point) for point in points]
    return result


def generate_setup_py(
    metadata: dict[str, Any],
    cfg: configparser.ConfigParser,
    root: Path,
) -> str:
    authors, author_email = author_values(metadata["authors"])
    maintainers, maintainer_email = author_values(metadata["maintainers"])
    urls = metadata["urls"]
    project_url = next(iter(urls.values()), "") if isinstance(urls, dict) else ""
    long_description, content_type = readme_expression(metadata["readme"])
    entry_points = build_entry_points(metadata)
    extensions, extension_backend = detect_extensions(metadata)
    setup_args = [
        f"name={metadata['name']!r}",
        f"version={metadata['version']!r}",
        f"description={metadata['description']!r}",
        "long_description=long_description",
        f"long_description_content_type={content_type}",
        f"author={authors!r}",
        f"author_email={author_email!r}",
        f"maintainer={maintainers!r}",
        f"maintainer_email={maintainer_email!r}",
        f"license={metadata['license']!r}",
        f"url={project_url!r}",
        f"keywords={python_literal(metadata['keywords'])}",
        f"classifiers={python_literal(metadata['classifiers'])}",
        f"python_requires={metadata['requires_python']!r}",
        f"install_requires={python_literal(metadata['dependencies'])}",
        f"extras_require={python_literal(metadata['optional_dependencies'])}",
        f"entry_points={python_literal(entry_points)}",
        "include_package_data=True",
        *build_package_arguments(metadata, cfg),
    ]
    if extensions:
        extension_literals = []
        for extension in extensions:
            extension_literals.append(
                "Extension("
                f"{extension['name']!r}, "
                f"sources={python_literal(extension.get('sources', []))}"
                ")"
            )
        setup_args.append(f"ext_modules=[{', '.join(extension_literals)}]")
    rendered_args = ",\n    ".join(setup_args)
    relative_readme = repr(str(Path(metadata["readme"].get("file", ""))))
    if isinstance(metadata["readme"], str):
        relative_readme = repr(metadata["readme"])
    return f'''#!/usr/bin/env python3
"""
Auto-generated from {root.name}/pyproject.toml.
This file intentionally preserves MANIFEST.in and setup.cfg by leaving them
available to setuptools rather than copying their contents into this file.
Detected extension backend: {extension_backend}
"""
from pathlib import Path
from setuptools import Extension, find_packages, setup
ROOT = Path(__file__).resolve().parent
README_FILE = ROOT / {relative_readme}
def read_text(relative_path: str) -> str:
    """Read a project file relative to setup.py."""
    path = ROOT / relative_path
    return path.read_text(encoding="utf-8") if path.is_file() else ""
long_description = {long_description}
setup(
    {rendered_args}
)
'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate setup.py from pyproject.toml."
    )
    parser.add_argument(
        "toml_path",
        nargs="?",
        type=Path,
        default=Path("pyproject.toml"),
        help="Path to pyproject.toml.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing setup.py.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    toml_path = args.toml_path.expanduser().resolve()
    if not toml_path.is_file():
        print(f"❌ Error: {toml_path} not found.")
        return 1
    files = project_files(toml_path)
    print(f"📂 Loading {files.pyproject}...")
    try:
        metadata = extract_metadata(load_toml(files.pyproject))
        cfg = parse_setup_cfg(files.setup_cfg)
        setup_py = generate_setup_py(metadata, cfg, files.root)
    except (OSError, ValueError, TypeError) as exc:
        print(f"❌ Error: {exc}", file=sys.stderr)
        return 1
    if files.setup_py.exists() and not args.force:
        print(f"⚠️  {files.setup_py} already exists. Use --force to overwrite.")
        return 0
    try:
        files.setup_py.write_text(setup_py, encoding="utf-8", newline="\n")
    except OSError as exc:
        print(f"❌ Error writing {files.setup_py}: {exc}", file=sys.stderr)
        return 1
    extensions, extension_backend = detect_extensions(metadata)
    print(f"✅ Generated {files.setup_py}")
    print("\n--- Conversion Summary ---")
    print(f"Project: {metadata['name']} v{metadata['version']}")
    print(f"Dependencies: {len(metadata['dependencies'])}")
    print(f"Optional deps: {len(metadata['optional_dependencies'])}")
    print(f"C-extensions: {extension_backend}")
    if files.setup_cfg.is_file():
        print("✅ Preserved: setup.cfg")
    if files.manifest.is_file():
        print("✅ Preserved: MANIFEST.in")
    if extensions:
        print(f"Extensions generated: {len(extensions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
