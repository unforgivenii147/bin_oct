#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import importlib.metadata
import importlib.util
import sys
from pathlib import Path

from dh import is_python_file

PACKAGE_MAPPING = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
    "google": "google-cloud-storage",
    "dotenv": "python-dotenv",
    "bs4": "beautifulsoup4",
    "fitz": "pymupdf",
    "skimage": "scikit-image",
    "telegram": "python-telegram-bot",
    "dateutil": "python-dateutil",
    "git": "GitPython",
    "jwt": "PyJWT",
    "OpenGL": "PyOpenGL",
}


def get_imports_from_file(path: Path):
    imports = set()
    try:
        with Path(path).open(encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(n.name.split(".")[0] for n in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.add(node.module.split(".")[0])
    except (SyntaxError, UnicodeDecodeError):
        pass
    return imports


def check_status(module_name) -> bool:
    try:
        importlib.metadata.distribution(module_name)
        return True
    except importlib.metadata.PackageNotFoundError:
        spec = importlib.util.find_spec(module_name)
        return spec is not None


def main() -> None:
    cwd = Path()
    output_file = cwd / "importz.txt"
    pip_script = cwd / "install_deps.sh"
    all_imports = set()
    local_names = {p.stem for p in cwd.glob("*.py")}
    local_names.update(
        {p.name for p in cwd.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    )
    std_libs = getattr(sys, "stdlib_module_names", set())
    for path in cwd.rglob("*"):
        if is_python_file(path) and path.name not in {"importz.txt", "install_deps.sh"}:
            all_imports.update(get_imports_from_file(path))
    third_party = [
        imp
        for imp in all_imports
        if imp not in std_libs and imp not in local_names and imp != "__future__"
    ]
    missing_for_pip = []
    already_installed = []
    for imp in sorted(third_party):
        if check_status(imp):
            already_installed.append(imp)
        else:
            pip_name = PACKAGE_MAPPING.get(imp, imp)
            missing_for_pip.append(pip_name)
    if third_party:
        output_file.write_text("\n".join(sorted(third_party)), encoding="utf-8")
        print(f"✅ Found {len(third_party)} 3rd-party dependencies.")
        if already_installed:
            print(f"📦 Already installed: {', '.join(already_installed)}")
        if missing_for_pip:
            install_cmd = f"pip install {' '.join(missing_for_pip)}"
            pip_script.write_text(f"#!/bin/sh\n{install_cmd}\n", encoding="utf-8")
            pip_script.chmod(pip_script.stat().st_mode | 73)
            print(f"⚠️  Missing: {', '.join(missing_for_pip)}")
            print(f"🚀 Run this to install missing: ./{pip_script.name}")
        else:
            if pip_script.exists():
                pip_script.unlink()
            print("✨ Environment is fully satisfied!")
    else:
        print("ℹ️ No 3rd-party imports found.")


if __name__ == "__main__":
    raise SystemExit(main())
