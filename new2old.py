#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import configparser
import tomllib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar


class Status(Enum):
    SUCCESS = ("✅", "\033[92m")
    ERROR = ("❌", "\033[91m")
    WARNING = ("⚠️ ", "\033[93m")
    INFO = ("ℹ️ ", "\033[94m")


def styled(text: str, color_code: str) -> str:
    return f"{color_code}{text}\033[0m"


def log(status: Status, message: str) -> None:
    print(f"{status.value[0]} {styled(message, status.value[1])}")


def log_plain(message: str) -> None:
    print(message)


@dataclass
class Author:
    name: str | None = None
    email: str | None = None

    def to_string(self) -> str | None:
        if self.name and self.email:
            return f"{self.name} <{self.email}>"
        elif self.name:
            return self.name
        elif self.email:
            return self.email
        return None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Author:
        return cls(name=data.get("name"), email=data.get("email"))


@dataclass
class License:
    text: str = ""
    path: str | None = None

    @classmethod
    def from_value(cls, value: str | dict[str, Any] | None) -> License:
        if not value:
            return cls()
        if isinstance(value, str):
            return cls(text=value)
        if isinstance(value, dict):
            if "text" in value:
                return cls(text=value["text"])
            if "file" in value:
                path = value["file"]
                try:
                    text = Path(path).read_text(encoding="utf-8")
                    return cls(text=text, path=path)
                except OSError:
                    return cls(path=path)
        return cls()


@dataclass
class Readme:
    content: str = ""
    content_type: str = "text/plain"

    @classmethod
    def from_value(cls, value: str | dict[str, Any] | None) -> Readme:
        if not value:
            return cls()
        if isinstance(value, str):
            return cls._from_path(value)
        if isinstance(value, dict):
            if "file" in value:
                content = cls._read_file(value["file"])
                content_type = value.get("content-type", "text/plain")
                return cls(content=content, content_type=content_type)
            if "text" in value:
                return cls(
                    content=value["text"],
                    content_type=value.get("content-type", "text/plain"),
                )
        return cls()

    @staticmethod
    def _from_path(path: str) -> Readme:
        content = Readme._read_file(path)
        if path.lower().endswith(".md"):
            content_type = "text/markdown"
        elif path.lower().endswith(".rst"):
            content_type = "text/x-rst"
        else:
            content_type = "text/plain"
        return Readme(content=content, content_type=content_type)

    @staticmethod
    def _read_file(path: str) -> str:
        try:
            return Path(path).read_text(encoding="utf-8")
        except OSError:
            return ""


@dataclass
class ProjectMetadata:
    name: str = ""
    version: str = "0.0.0"
    description: str = ""
    readme: Readme = field(default_factory=Readme)
    requires_python: str = ""
    license: License = field(default_factory=License)
    authors: list[Author] = field(default_factory=list)
    maintainers: list[Author] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    classifiers: list[str] = field(default_factory=list)
    urls: dict[str, str] = field(default_factory=dict)
    scripts: dict[str, str] = field(default_factory=dict)
    gui_scripts: dict[str, str] = field(default_factory=dict)
    entry_points: dict[str, dict[str, str]] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    optional_dependencies: dict[str, list[str]] = field(default_factory=dict)
    build_backend: str = ""
    build_requires: list[str] = field(default_factory=list)
    tool_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_toml_dict(cls, data: dict[str, Any]) -> ProjectMetadata:
        project = data.get("project", {})
        build_system = data.get("build-system", {})
        tool = data.get("tool", {})
        authors = [
            Author.from_dict(a)
            for a in project.get("authors", [])
            if isinstance(a, dict)
        ]
        maintainers = [
            Author.from_dict(m)
            for m in project.get("maintainers", [])
            if isinstance(m, dict)
        ]
        entry_points: dict[str, dict[str, str]] = {}
        for group_name, group_data in project.get("entry-points", {}).items():
            if isinstance(group_data, dict):
                entry_points[group_name] = group_data
        return cls(
            name=project.get("name", ""),
            version=project.get("version", "0.0.0"),
            description=project.get("description", ""),
            readme=Readme.from_value(project.get("readme")),
            requires_python=project.get("requires-python", ""),
            license=License.from_value(project.get("license")),
            authors=authors,
            maintainers=maintainers,
            keywords=project.get("keywords", []),
            classifiers=project.get("classifiers", []),
            urls=project.get("urls", {}),
            scripts=project.get("scripts", {}),
            gui_scripts=project.get("gui-scripts", {}),
            entry_points=entry_points,
            dependencies=project.get("dependencies", []),
            optional_dependencies=project.get("optional-dependencies", {}),
            build_backend=build_system.get("build-backend", ""),
            build_requires=build_system.get("requires", []),
            tool_config=tool,
        )


@dataclass
class SetupCfgData:
    packages_find: dict[str, str] = field(default_factory=dict)
    package_data: dict[str, list[str]] = field(default_factory=dict)
    data_files: list[tuple[str, list[str]]] = field(default_factory=list)
    entry_points: dict[str, list[str]] = field(default_factory=dict)
    options: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_text(cls, content: str | None) -> SetupCfgData:
        if not content:
            return cls()
        try:
            parser = configparser.ConfigParser()
            parser.read_string(content)
        except configparser.Error:
            return cls()
        instance = cls()
        if parser.has_section("options.packages.find"):
            instance.packages_find = dict(parser.items("options.packages.find"))
        if parser.has_section("options") and parser.has_option(
            "options", "package_data"
        ):
            pkg_data_str = parser.get("options", "package_data")
            instance.package_data = {}
        if parser.has_section("options.data_files"):
            for target, files_str in parser.items("options.data_files"):
                files = [f.strip() for f in files_str.split(",") if f.strip()]
                instance.data_files.append((target, files))
        if parser.has_section("options.entry_points"):
            for group, entries_str in parser.items("options.entry_points"):
                entries = [e.strip() for e in entries_str.split("\n") if e.strip()]
                instance.entry_points[group] = entries
        return instance


class CExtensionBackend(Enum):
    NONE = "none"
    SETUPTOOLS = "setuptools"
    SCIKIT_BUILD = "scikit-build"
    MESON = "meson-python"
    CMAKE = "cmake"


@dataclass
class CExtensionInfo:
    backend: CExtensionBackend = CExtensionBackend.NONE
    has_extensions: bool = False

    @classmethod
    def detect(cls, metadata: ProjectMetadata) -> CExtensionInfo:
        tool_config = metadata.tool_config
        if "setuptools" in tool_config and tool_config["setuptools"].get("ext-modules"):
            return cls(backend=CExtensionBackend.SETUPTOOLS, has_extensions=True)
        if "scikit-build" in tool_config or "scikit-build-core" in tool_config:
            return cls(backend=CExtensionBackend.SCIKIT_BUILD, has_extensions=True)
        if "meson-python" in tool_config:
            return cls(backend=CExtensionBackend.MESON, has_extensions=True)
        for req in metadata.build_requires:
            if "meson-python" in req:
                return cls(backend=CExtensionBackend.MESON, has_extensions=True)
        return cls()


class CodeGenerator:
    TEMPLATE: ClassVar[str] = '''#!/usr/bin/env python3
"""
Auto-generated setup.py from pyproject.toml.
This file is generated for compatibility with tools that require setup.py.
For modern packaging, consider using pyproject.toml directly with build tools
like pip, build, or uv.
C-extensions backend: {cext_backend}
"""
from __future__ import annotations
import os
from pathlib import Path
{imports}
{setup_func}
if __name__ == "__main__":
    setup(
{setup_kwargs}
    )
'''

    @staticmethod
    def quote_string(s: str) -> str:
        return f'"{s.replace(chr(34), chr(92) + chr(34))}"'

    @staticmethod
    def format_list(items: list[str], indent: int = 8) -> str:
        if not items:
            return "[]"
        prefix = " " * indent
        formatted = ",\n".join(
            f"{prefix}{CodeGenerator.quote_string(item)}" for item in items
        )
        return f"[\n{formatted}\n{' ' * (indent - 4)}]"

    @staticmethod
    def format_dict(
        data: dict[str, str | list[str]], indent: int = 8, value_is_list: bool = False
    ) -> str:
        if not data:
            return "{}"
        prefix = " " * indent
        items = []
        for key, value in data.items():
            if value_is_list and isinstance(value, list):
                value_str = CodeGenerator.format_list(value, indent + 4).replace(
                    "\n", f"\n{prefix}"
                )
                items.append(f"{prefix}{CodeGenerator.quote_string(key)}: {value_str}")
            else:
                items.append(
                    f"{prefix}{CodeGenerator.quote_string(key)}: {CodeGenerator.quote_string(str(value))}"
                )
        return "{\n" + ",\n".join(items) + f"\n{' ' * (indent - 4)}}}"

    @classmethod
    def generate_imports(cls, cext_info: CExtensionInfo) -> str:
        imports = ["from setuptools import setup, find_packages"]
        if cext_info.backend == CExtensionBackend.SETUPTOOLS:
            imports.append("from setuptools import Extension")
        elif cext_info.backend == CExtensionBackend.SCIKIT_BUILD:
            imports = ["from skbuild import setup"]
        return "\n".join(imports)

    @classmethod
    def generate_setup_function(
        cls,
        metadata: ProjectMetadata,
        cext_info: CExtensionInfo,
        setup_cfg: SetupCfgData,
    ) -> str:
        return ""

    @classmethod
    def generate_setup_kwargs(
        cls,
        metadata: ProjectMetadata,
        cext_info: CExtensionInfo,
        setup_cfg: SetupCfgData,
    ) -> str:
        kwargs_parts = []
        kwargs_parts.append(f"        name={cls.quote_string(metadata.name)},")
        kwargs_parts.append(f"        version={cls.quote_string(metadata.version)},")
        if metadata.description:
            kwargs_parts.append(
                f"        description={cls.quote_string(metadata.description)},"
            )
        if metadata.readme.content:
            readme_content = metadata.readme.content.replace('"""', r"\"\"\"")
            kwargs_parts.append(
                f"        long_description={cls.quote_string(readme_content)},\n"
                f"        long_description_content_type={cls.quote_string(metadata.readme.content_type)},"
            )
        author_strs = [a.to_string() for a in metadata.authors if a.to_string()]
        if author_strs:
            kwargs_parts.append(
                f"        author={cls.quote_string(', '.join(author_strs))},"
            )
        maintainer_strs = [m.to_string() for m in metadata.maintainers if m.to_string()]
        if maintainer_strs:
            kwargs_parts.append(
                f"        maintainer={cls.quote_string(', '.join(maintainer_strs))},"
            )
        if metadata.license.text:
            kwargs_parts.append(
                f"        license={cls.quote_string(metadata.license.text)},"
            )
        elif metadata.license.path:
            kwargs_parts.append(
                f"        license_files={cls.format_list([metadata.license.path], 8)},"
            )
        if metadata.requires_python:
            kwargs_parts.append(
                f"        python_requires={cls.quote_string(metadata.requires_python)},"
            )
        if metadata.keywords:
            kwargs_parts.append(
                f"        keywords={cls.quote_string(' '.join(metadata.keywords))},"
            )
        if metadata.classifiers:
            kwargs_parts.append(
                f"        classifiers={cls.format_list(metadata.classifiers, 8)},"
            )
        if metadata.urls:
            kwargs_parts.append(
                f"        project_urls={cls.format_dict(metadata.urls, 8)},"
            )
        if setup_cfg.packages_find:
            find_kwargs = ", ".join(
                f"{k}={cls.quote_string(v)}" for k, v in setup_cfg.packages_find.items()
            )
            kwargs_parts.append(f"        packages=find_packages({find_kwargs}),")
        else:
            kwargs_parts.append("        packages=find_packages(),")
        if metadata.dependencies:
            kwargs_parts.append(
                f"        install_requires={cls.format_list(metadata.dependencies, 8)},"
            )
        if metadata.optional_dependencies:
            kwargs_parts.append(
                f"        extras_require={cls.format_dict(metadata.optional_dependencies, 8, value_is_list=True)},"
            )
        entry_points_dict = {}
        if metadata.scripts:
            entry_points_dict["console_scripts"] = [
                f"{name} = {target}" for name, target in metadata.scripts.items()
            ]
        if metadata.gui_scripts:
            entry_points_dict["gui_scripts"] = [
                f"{name} = {target}" for name, target in metadata.gui_scripts.items()
            ]
        for group, entries in metadata.entry_points.items():
            entry_points_dict[group] = [
                f"{name} = {target}" for name, target in entries.items()
            ]
        if setup_cfg.entry_points:
            for group, entries in setup_cfg.entry_points.items():
                if group in entry_points_dict:
                    entry_points_dict[group].extend(entries)
                else:
                    entry_points_dict[group] = entries
        if entry_points_dict:
            kwargs_parts.append(
                f"        entry_points={cls.format_dict(entry_points_dict, 8, value_is_list=True)},"
            )
        if setup_cfg.package_data:
            kwargs_parts.append(
                f"        package_data={cls.format_dict(setup_cfg.package_data, 8, value_is_list=True)},"
            )
        if setup_cfg.data_files:
            data_files_str = ",\n".join(
                f"            ({cls.quote_string(target)}, {cls.format_list(files, 12)})"
                for target, files in setup_cfg.data_files
            )
            kwargs_parts.append(f"        data_files=[\n{data_files_str}\n        ],")
        if (
            cext_info.has_extensions
            and cext_info.backend == CExtensionBackend.SETUPTOOLS
        ):
            kwargs_parts.append("        ext_modules=ext_modules,")
        elif (
            cext_info.has_extensions
            and cext_info.backend == CExtensionBackend.SCIKIT_BUILD
        ):
            kwargs_parts.append("        cmake_args=[],")
        return "\n".join(kwargs_parts)

    @classmethod
    def generate(
        cls,
        metadata: ProjectMetadata,
        cext_info: CExtensionInfo,
        setup_cfg: SetupCfgData,
    ) -> str:
        imports = cls.generate_imports(cext_info)
        setup_kwargs = cls.generate_setup_kwargs(metadata, cext_info, setup_cfg)
        setup_func = cls.generate_setup_function(metadata, cext_info, setup_cfg)
        if (
            cext_info.has_extensions
            and cext_info.backend == CExtensionBackend.SETUPTOOLS
        ):
            setup_func = cls._generate_ext_modules(metadata)
        return cls.TEMPLATE.format(
            cext_backend=cext_info.backend.value,
            imports=imports,
            setup_func=setup_func,
            setup_kwargs=setup_kwargs,
        )

    @classmethod
    def _generate_ext_modules(cls, metadata: ProjectMetadata) -> str:
        ext_modules = metadata.tool_config.get("setuptools", {}).get("ext-modules", [])
        if not ext_modules:
            return ""
        module_defs = []
        for module in ext_modules:
            if isinstance(module, dict):
                name = module.get("name", "")
                sources = module.get("sources", [])
                include_dirs = module.get("include-dirs", [])
                args = [f"    Extension({cls.quote_string(name)},"]
                args.append(f"        sources={cls.format_list(sources, 8)},")
                if include_dirs:
                    args.append(
                        f"        include_dirs={cls.format_list(include_dirs, 8)},"
                    )
                args.append("    ),")
                module_defs.append("\n".join(args))
            elif isinstance(module, str):
                module_defs.append(
                    f"    Extension({cls.quote_string(module)}, sources=[{cls.quote_string(module)}.c]),"
                )
        if module_defs:
            return "ext_modules = [\n" + "\n".join(module_defs) + "\n]\n"
        return ""


def read_file_safe(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def write_file_safe(path: Path, content: str, force: bool = False) -> bool:
    if path.exists() and not force:
        log(Status.WARNING, f"File {path} already exists. Use --force to overwrite.")
        return False
    try:
        path.write_text(content, encoding="utf-8")
        return True
    except OSError as e:
        log(Status.ERROR, f"Failed to write {path}: {e}")
        return False


def preserve_file(path: Path) -> None:
    if path.exists():
        log(Status.INFO, f"Preserving existing {path.name}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert pyproject.toml to setup.py while preserving setup.cfg and MANIFEST.in."
    )
    parser.add_argument(
        "pyproject_path",
        nargs="?",
        default="pyproject.toml",
        help="Path to pyproject.toml (default: pyproject.toml)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing setup.py",
    )
    args = parser.parse_args()
    pyproject_path = Path(args.pyproject_path)
    if not pyproject_path.exists():
        log(Status.ERROR, f"File not found: {pyproject_path}")
        return 1
    log(Status.INFO, f"Reading {pyproject_path}")
    try:
        with pyproject_path.open("rb") as f:
            toml_data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        log(Status.ERROR, f"Invalid TOML in {pyproject_path}: {e}")
        return 1
    except OSError as e:
        log(Status.ERROR, f"Failed to read {pyproject_path}: {e}")
        return 1
    if "project" not in toml_data:
        log(Status.ERROR, "No [project] section found in pyproject.toml")
        return 1
    log(Status.INFO, "Parsing project metadata")
    metadata = ProjectMetadata.from_toml_dict(toml_data)
    if not metadata.name:
        log(Status.ERROR, "Missing required field: project.name")
        return 1
    setup_cfg_path = pyproject_path.parent / "setup.cfg"
    setup_cfg_content = read_file_safe(setup_cfg_path)
    setup_cfg = SetupCfgData.from_text(setup_cfg_content)
    if setup_cfg_content:
        log(Status.INFO, "Parsed existing setup.cfg")
        preserve_file(setup_cfg_path)
    cext_info = CExtensionInfo.detect(metadata)
    if cext_info.has_extensions:
        log(Status.INFO, f"Detected C-extension backend: {cext_info.backend.value}")
    log(Status.INFO, "Generating setup.py")
    generator = CodeGenerator()
    setup_content = generator.generate(metadata, cext_info, setup_cfg)
    setup_path = pyproject_path.parent / "setup.py"
    if write_file_safe(setup_path, setup_content, args.force):
        log(Status.SUCCESS, f"Generated {setup_path}")
    else:
        return 1
    manifest_path = pyproject_path.parent / "MANIFEST.in"
    preserve_file(manifest_path)
    log_plain("")
    log(Status.SUCCESS, "Conversion complete!")
    log_plain("")
    log_plain(f"  📄 Generated: {setup_path.name}")
    log_plain(
        "  📄 Preserved: setup.cfg" if setup_cfg_content else "  📄 No setup.cfg found"
    )
    log_plain(
        "  📄 Preserved: MANIFEST.in"
        if manifest_path.exists()
        else "  📄 No MANIFEST.in found"
    )
    if cext_info.has_extensions:
        log_plain(f"  🔧 C-extension backend: {cext_info.backend.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
