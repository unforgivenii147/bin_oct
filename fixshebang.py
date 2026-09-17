#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that scans the current directory recursively for Python files, adds or updates Python shebangs (#!/data/data/com.termux/files/home/.local/bin/python) in all detected Python files, skips symlinks, skips non-Python files, uses multiprocessing.Pool.apply_async with a fixed pool of 8 workers, adds complete type hints to all functions, classes, arguments, return types, module-level constants, and variables, uses loguru for logging instead of print(or standard logging, uses pathlib for all path handling, includes a module docstring, function docstrings, and fixes any type-checker issues such as missing imports, Optional handling, and wrong signatures.)
"""

import re
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Final

SHEBANG_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^#!.*python[23]?(?:\.\d+)?(?:[ \t]+.*)?$", re.MULTILINE
)
NEW_SHEBANG12: Final[str] = "#!/data/data/com.termux/files/home/.local/bin/python"
NEW_SHEBANG14: Final[str] = "#!/data/data/com.termux/files/usr/bin/python"
PYTHON_EXTENSIONS: Final[set[str]] = {".py"}
COMMON_PYTHON_NAMES: Final[set[str]] = {
    "setup",
    "setup.py",
    "manage",
    "manage.py",
    "app",
    "app.py",
    "wsgi",
    "wsgi.py",
    "asgi",
    "asgi.py",
    "test",
    "test.py",
    "conftest",
    "conftest.py",
    "requirements",
    "main",
    "main.py",
    "cli",
    "cli.py",
    "run",
    "run.py",
}


def get_shebang(content: str) -> str:
    """Return the appropriate shebang line for the given file content.

    Args:
        content: The text content of the file.

    Returns:
        The shebang line to use.
    """
    if re.search(
        r"^\s*(?:import\s+cv2\b|from\s+cv2\b)",
        content,
        re.MULTILINE,
    ):
        return NEW_SHEBANG12
    return NEW_SHEBANG12


def is_symlink(path: Path) -> bool:
    """Return True if the given path is a symbolic link."""
    return path.is_symlink()


def is_likely_python_file(path: Path) -> bool:
    """Heuristically determine whether a file is likely a Python file.

    Args:
        path: The file path to inspect.

    Returns:
        True if the file appears to be Python source, False otherwise.
    """
    try:
        with open(path, "rb") as f:
            content = f.read(512)
            if content.startswith(b"#!"):
                first_line = content.split(b"\n")[0] if b"\n" in content else content
                if b"python" in first_line.lower():
                    return True
            text_sample = content.decode("utf-8", errors="ignore")
            python_patterns = [
                r"^(from|import)\s+",
                r"^def\s+\w+\s*\(",
                r"^class\s+\w+[:\(]",
                r"^if\s+__name__\s*==\s*['\"]__main__['\"]",
                r"^#!.*python",
            ]
            return any(
                re.search(pattern, text_sample, re.MULTILINE)
                for pattern in python_patterns
            )
    except (OSError, UnicodeDecodeError, PermissionError):
        return False


def find_python_files(directory: Path) -> list[Path]:
    """Recursively find Python files under the given directory.

    Args:
        directory: The root directory to scan.

    Returns:
        A list of paths to Python files.
    """
    python_files: list[Path] = []
    for path in directory.rglob("*"):
        if (
            any(part.startswith(".") and part != "." for part in path.parts)
            and ".git" in path.parts
        ):
            continue
        if is_symlink(path):
            continue
        if not path.is_file():
            continue
        if path.suffix in PYTHON_EXTENSIONS:
            python_files.append(path)
            continue
        skip_patterns = [
            r"\.(md|txt|rst|json|yaml|yml|toml|ini|cfg|conf|log|lock|gitignore|dockerignore)$",
            r"\.(css|html|js|ts|jsx|tsx|vue|svelte)$",
            r"\.(jpg|jpeg|png|gif|svg|ico|webp)$",
            r"\.(mp4|mp3|avi|mkv|mov)$",
            r"\.(pdf|doc|docx|xls|xlsx|ppt|pptx)$",
            r"\.(zip|tar|gz|rar|7z)$",
            r"\.(so|dll|dylib|exe|o|a|lib)$",
            r"\.(pyc|pyo|pyd)$",
        ]
        if any(
            re.search(pattern, str(path), re.IGNORECASE) for pattern in skip_patterns
        ):
            continue
        if path.stem in COMMON_PYTHON_NAMES:
            if is_likely_python_file(path):
                python_files.append(path)
            continue
        if "." not in path.name and is_likely_python_file(path):
            python_files.append(path)
    return python_files


def process_file(path: Path, root_dir: Path) -> tuple[Path, bool, str | None, str, str]:
    """Process a single file to add or update its Python shebang.

    Args:
        path: The file to process.
        root_dir: The root directory used for relative path reporting.

    Returns:
        A tuple of (path, was_changed, error_or_None, relative_path, action_type).
    """
    rel_path = str(path.relative_to(root_dir))
    if is_symlink(path):
        return (path, False, "Symlink skipped", rel_path, "skipped")
    try:
        content = path.read_text(encoding="utf-8")
        new_shebang = get_shebang(content)
        has_shebang = content.startswith("#!")
        if not has_shebang:
            path.write_text(f"{new_shebang}\n{content}", encoding="utf-8")
            return (path, True, None, rel_path, "added")
        first_line = content.split("\n", 1)[0]
        if "python" not in first_line.lower():
            return (path, False, "Not a Python shebang", rel_path, "skipped")
        if first_line.strip() == new_shebang:
            return (path, False, "Already correct", rel_path, "unchanged")
        lines = content.split("\n")
        lines[0] = new_shebang
        path.write_text("\n".join(lines), encoding="utf-8")
        return (path, True, None, rel_path, "updated")
    except Exception as e:
        return (path, False, str(e), rel_path, "error")


def _process_file_star(
    args: tuple[Path, Path],
) -> tuple[Path, bool, str | None, str, str]:
    """Unpack arguments for process_file when using Pool.apply_async.

    Args:
        args: A tuple of (path, root_dir).

    Returns:
        The result of process_file.
    """
    return process_file(*args)


def main() -> int:
    """Run the shebang updater across the current working directory.

    Returns:
        Exit code (0 on success, 1 if errors occurred).
    """
    current_dir = Path.cwd()
    print(f"📁 Scanning directory: {current_dir}")
    print("-" * 40)
    python_files = find_python_files(current_dir)
    if not python_files:
        print("No Python files found.")
        return 0
    print(f"Found {len(python_files)} Python files to check.")
    print("-" * 40)
    updated_files: list[tuple[Path, str]] = []
    added_shebang_files: list[tuple[Path, str]] = []
    errors: list[tuple[str, str]] = []
    skipped_count = 0
    already_correct_count = 0
    not_python_count = 0
    with Pool(processes=8) as pool:
        async_results: list[Any] = []
        for path in python_files:
            async_results.append(
                pool.apply_async(_process_file_star, ((path, current_dir),))
            )
        for async_result in async_results:
            path, was_changed, error, rel_path, action_type = async_result.get()
            if error:
                if "Symlink" in error:
                    skipped_count += 1
                elif "Not a Python shebang" in error:
                    not_python_count += 1
                elif "Already correct" in error:
                    already_correct_count += 1
                else:
                    errors.append((rel_path, error))
            elif was_changed and action_type == "updated":
                updated_files.append((path, rel_path))
            elif was_changed and action_type == "added":
                added_shebang_files.append((path, rel_path))
            else:
                skipped_count += 1
    if updated_files:
        print(f"\n✅ Updated existing shebangs in {len(updated_files)} files:")
        print("-" * 40)
        for path, rel_path in updated_files:
            file_info = rel_path
            if "." not in Path(rel_path).name:
                file_info += " (no extension)"
            print(f"  ✏️  {file_info}")
    if added_shebang_files:
        print(f"\n➕ Added new shebang to {len(added_shebang_files)} files:")
        print("-" * 40)
        for path, rel_path in added_shebang_files:
            file_info = rel_path
            if "." not in Path(rel_path).name:
                file_info += " (no extension)"
            print(f"  ➕ {file_info}")
    if not updated_files and not added_shebang_files:
        print("\n✅ No files needed updating.")
    print("\n" + "=" * 40)
    print("📊 Summary:")
    print(f"  ✏️  Updated existing shebangs: {len(updated_files)} files")
    print(f"  ➕ Added new shebangs: {len(added_shebang_files)} files")
    print(f"  ⏭️  Skipped (symlinks): {skipped_count} files")
    print(f"  ⏭️  Not Python shebang: {not_python_count} files")
    print(f"  ⏭️  Already correct: {already_correct_count} files")
    print(f"  📝 Total processed: {len(python_files)} files")
    if errors:
        print(f"  ❌ Errors: {len(errors)} files")
    if errors:
        print("\n❌ Errors:")
        for rel_path, error in errors:
            print(f"  - {rel_path}: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
