#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
from pathlib import Path


def is_valid_module_file(path: Path) -> bool:
    """Return True if the path is a candidate Python module file.

    Excludes non-`.py` files, dunder files (e.g. `__main__.py`),
    and private files whose name starts with an underscore.
    """
    if not path.is_file():
        return False
    if path.suffix != ".py":
        return False
    if path.name.startswith("_"):
        return False
    return True


def is_valid_subpackage(path: Path) -> bool:
    """Return True if the path is a subpackage (dir with __init__.py).

    Skips private directories starting with an underscore.
    """
    if not path.is_dir():
        return False
    if path.name.startswith("_"):
        return False
    return (path / "__init__.py").is_file()


def parse_module(path: Path) -> ast.Module | None:
    """Parse a Python file into an AST, returning None on failure."""
    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None

    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError:
        return None


def get_public_functions(tree: ast.Module) -> list[str]:
    """Collect names of top-level public functions.

    Skips names starting with '_' and the special name 'main'.
    """
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            if node.name == "main":
                continue
            names.append(node.name)
    return names


def get_public_classes(tree: ast.Module) -> list[str]:
    """Collect names of top-level public classes (not starting with '_')."""
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                names.append(node.name)
    return names


def has_only_main(tree: ast.Module) -> bool:
    """Return True if the module defines `main` and no other public members.

    Private names (starting with '_') are ignored. If `main` is the only
    public top-level definition, we treat the module as a script entry
    point and skip re-exporting it.
    """
    has_main = False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "main":
                has_main = True
                continue
            if node.name.startswith("_"):
                continue
            return False  # found another public function
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            return False  # found a public class
    return has_main


def build_init_content(project_dir: Path) -> str:
    """Build the content for __init__.py from the given directory.

    - Imports public functions and classes from each sibling module.
    - Imports subpackages as modules.
    - Skips dunder/private files and directories.
    - Skips modules that only define `main` (script entry points).
    - Appends an `__all__` list of all re-exported names.
    """
    import_lines: list[str] = []
    exported_names: list[str] = []

    module_files = sorted(
        (
            p
            for p in project_dir.iterdir()
            if is_valid_module_file(p) and p.name != "__init__.py"
        ),
        key=lambda p: p.name,
    )

    subpackages = sorted(
        (p for p in project_dir.iterdir() if is_valid_subpackage(p)),
        key=lambda p: p.name,
    )

    for module_path in module_files:
        tree = parse_module(module_path)
        if tree is None:
            continue

        # Skip modules that exist only as a `main` entry point.
        if has_only_main(tree):
            continue

        module_name = module_path.stem
        functions = get_public_functions(tree)
        classes = get_public_classes(tree)

        # Preserve source order while removing duplicates.
        names = list(dict.fromkeys(classes + functions))

        if names:
            import_list = ", ".join(names)
            import_lines.append(
                f"from .{module_name.replace('-', '_')} import {import_list}"
            )
            exported_names.extend(names)
        else:
            import_lines.append(f"from . import {module_name}")
            # Re-export the module itself when it has no public members.
            exported_names.append(module_name)

    for pkg in subpackages:
        import_lines.append(f"from . import {pkg.name}")
        exported_names.append(pkg.name)

    # Deduplicate __all__ while preserving order.
    exported_names = list(dict.fromkeys(exported_names))

    parts: list[str] = []
    if import_lines:
        parts.append("\n".join(import_lines))

    if exported_names:
        all_block = ["__all__ = ["]
        for name in exported_names:
            all_block.append(f'    "{name}",')
        all_block.append("]")
        parts.append("\n".join(all_block))

    return "\n\n".join(parts) + "\n" if parts else ""


def clean_content(text: str) -> str:
    lines = text.splitlines(keepends=True)
    result = []
    for line in lines:
        if line.startswith("from"):
            if not line.startswith("from . import "):
                result.append(line)
        else:
            result.append(line)
    return "".join(result)


def create_init_file(project_dir: Path | None = None) -> Path:
    """Create (or overwrite) __init__.py in the given project directory.

    Args:
        project_dir: Target directory. Defaults to the current working dir.

    Returns:
        The path to the created __init__.py file.

    Raises:
        NotADirectoryError: If the given path is not a directory.
    """
    if project_dir is None:
        project_dir = Path.cwd()

    project_dir = project_dir.resolve()
    if not project_dir.is_dir():
        raise NotADirectoryError(f"{project_dir} is not a directory")

    init_path = project_dir / "__init__.py"
    content = build_init_content(project_dir)
    content = clean_content(content)
    init_path.write_text(content, encoding="utf-8")

    return init_path


if __name__ == "__main__":
    create_init_file()
