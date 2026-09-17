#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import sys
import tempfile
import zipfile
from email.parser import Parser
from pathlib import Path

EXT_SUFFIXES = (".so", ".pyd", ".dll")


def read_entry_points(root: Path) -> dict[str, list[str]]:
    dist_info = next(root.glob("*.dist-info"), None)
    if not dist_info:
        return {}
    ep_file = dist_info / "entry_points.txt"
    if not ep_file.exists():
        return {}
    sections: dict[str, list[str]] = {}
    current_section = None
    for line in ep_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1]
            sections[current_section] = []
            continue
        if current_section:
            sections[current_section].append(line)
    return sections


def extract_wheel(whl: Path, dst: Path) -> None:
    with zipfile.ZipFile(whl) as zf:
        zf.extractall(dst)


def load_root(input_path: Path) -> Path:
    if input_path.is_dir():
        return input_path.resolve()
    if input_path.suffix == ".whl":
        tmp = Path(tempfile.mkdtemp())
        extract_wheel(input_path, tmp)
        return tmp
    msg = "Input must be a .whl file or an unzipped wheel directory"
    raise SystemExit(msg)


def read_metadata(root: Path) -> dict:
    dist_info = next(root.glob("*.dist-info"), None)
    if not dist_info:
        msg = "No .dist-info directory found"
        raise RuntimeError(msg)
    meta_file = dist_info / "METADATA"
    meta = Parser().parsestr(meta_file.read_text())
    return {
        "name": meta["Name"],
        "version": meta["Version"],
        "summary": meta.get("Summary", ""),
        "install_requires": meta.get_all("Requires-Dist") or [],
    }


def find_extensions(root: Path) -> list[str]:
    return [
        ".".join(f.relative_to(root).with_suffix("").parts)
        for f in root.rglob("*")
        if f.suffix in EXT_SUFFIXES
    ]


def generate_setup_py(
    meta: dict, extensions: list[str], entry_points: dict[str, list[str]]
) -> str:
    ext_block = (
        "from setuptools import Extension\n\next_modules = [\n"
        + "\n".join(
            f"""    Extension("{m}", sources=["{m.replace(".", "/")}.*"]),"""
            for m in extensions
        )
        + "\n]\n"
        if extensions
        else "ext_modules = []\n"
    )
    ep_block = ""
    if entry_points:
        formatted = "{\n"
        for section, values in entry_points.items():
            formatted += f'        "{section}": [\n'
            for v in values:
                formatted += f'            "{v}",\n'
            formatted += "        ],\n"
        formatted += "    }"
        ep_block = f"    entry_points={formatted},\n"
    return f"""from setuptools import setup, find_packages\n{ext_block}\nsetup(\n    name="{meta["name"]}",\n    version="{meta["version"]}",\n    description="{meta["summary"]}",\n    packages=find_packages() or ["."],\n    install_requires={meta["install_requires"]},\n    ext_modules=ext_modules,\n{ep_block})\n"""


def generate_pyproject_toml() -> str:
    return '[build-system]\nrequires = ["setuptools>=61", "wheel"]\nbuild-backend = "setuptools.build_meta"\n'


def main() -> None:
    if len(sys.argv) != 2:
        msg = "Usage: python mk_setuppy.py <wheel.whl | unzipped-dir>"
        raise SystemExit(msg)
    input_path = Path(sys.argv[1]).resolve()
    root = load_root(input_path)
    meta = read_metadata(root)
    entry_points = read_entry_points(root)
    extensions = find_extensions(root)
    out_dir = Path("output") / meta["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root, out_dir, dirs_exist_ok=True)
    (out_dir / "setup.py").write_text(generate_setup_py(meta, extensions, entry_points))
    (out_dir / "pyproject.toml").write_text(generate_pyproject_toml())
    print(f"✔ setup.py generated for {meta['name']}")
    print("✔ binary extensions detected" if extensions else "✔ pure Python package")


if __name__ == "__main__":
    raise SystemExit(main())
