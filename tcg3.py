#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TERMUX_SHEBANGS = {
    "python": "#!/data/data/com.termux/files/usr/bin/python",
    "bash": "#!/data/data/com.termux/files/usr/bin/bash",
    "sh": "#!/data/data/com.termux/files/usr/bin/sh",
}
SCRIPT_DIRS = {
    Path.home() / "bin",
    Path.home() / "bashbin",
    Path.home() / ".local" / "bin",
}


def get_clipboard_content() -> str:
    try:
        result = subprocess.run(
            ["termux-clipboard-get"], capture_output=True, text=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Failed to read clipboard: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("Error: termux-clipboard-get not found", file=sys.stderr)
        sys.exit(1)


def detect_script_type(content: str) -> str:
    if not content.strip():
        return "unknown"
    first_line = content.lstrip().split("\n")[0] if content else ""
    if first_line.startswith("#!"):
        if "python" in first_line.lower():
            return "python"
        elif "bash" in first_line.lower() or "sh" in first_line.lower():
            return "bash"
    preview = content[:500].lower()
    python_indicators = [
        "import ",
        "from ",
        "def ",
        "class ",
        "if __name__",
        "print(",
        "self.",
        "__init__",
        "async def",
        "await ",
    ]
    bash_indicators = [
        "echo ",
        "cd ",
        "export ",
        "if [",
        "if [[",
        "then",
        "elif",
        "fi",
        "done",
        "while ",
        "for ",
        "case ",
        "esac",
        "$(",
        "${",
        "`",
        "#!/bin/bash",
        "#!/bin/sh",
    ]
    python_score = sum(1 for ind in python_indicators if ind in preview)
    bash_score = sum(1 for ind in bash_indicators if ind in preview)
    if python_score > bash_score:
        return "python"
    elif bash_score > python_score:
        return "bash"
    else:
        return "bash"


def get_shebang_from_filename(filename: str) -> str | None:
    path = Path(filename)
    suffix = path.suffix.lower()
    if suffix in [".py", ".pyw"]:
        return "python"
    elif suffix in [".sh", ".bash"] or suffix in [".rb", ".pl", ".js", ".go", ".rs"]:
        return "bash"
    return None


def replace_shebang(content: str, script_type: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].startswith("#!"):
        lines.pop(0)
        if lines and lines[0].startswith("#!"):
            lines.pop(0)
    if script_type == "python":
        lines.insert(0, TERMUX_SHEBANGS["python"])
    elif script_type == "bash":
        lines.insert(0, TERMUX_SHEBANGS["bash"])
    else:
        lines.insert(0, TERMUX_SHEBANGS["bash"])
    result = "\n".join(lines)
    return result if result.endswith("\n") else result + "\n"


def create_symlink(script_path: Path) -> None:
    if script_path.suffix:
        symlink_path = script_path.parent / script_path.stem
        if not symlink_path.exists():
            try:
                symlink_path.symlink_to(script_path)
                print(f"  → Created symlink: {symlink_path.name}")
            except OSError as e:
                print(f"  ⚠️  Failed to create symlink: {e}", file=sys.stderr)
        elif symlink_path.is_symlink():
            print(f"  → Symlink already exists: {symlink_path.name}")
        else:
            print(f"  ⚠️  {symlink_path.name} exists but is not a symlink")


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <filename>", file=sys.stderr)
        print(f"Example: {sys.argv[0]} myscript.py", file=sys.stderr)
        print(f"Example: {sys.argv[0]} mytool", file=sys.stderr)
        sys.exit(1)
    filename = sys.argv[1]
    output_path = Path(filename)
    cwd = Path.cwd()
    is_script_dir = cwd in SCRIPT_DIRS
    content = get_clipboard_content()
    if not content.strip():
        print("⚠️  Clipboard is empty, creating empty file")
        content = "\n"
        if is_script_dir:
            script_type = get_shebang_from_filename(filename) or "bash"
            content = replace_shebang(content, script_type)
            print(f"✓ Added {script_type} shebang (inferred from filename)")
    else:
        script_type = None
        if is_script_dir:
            script_type = get_shebang_from_filename(filename)
            if not script_type:
                script_type = detect_script_type(content)
                print(f"✓ Detected {script_type} script from content")
            else:
                print(f"✓ Detected {script_type} script from filename extension")
        if is_script_dir and script_type:
            content = replace_shebang(content, script_type)
    try:
        output_path.write_text(content)
        print(f"✓ Created: {output_path}")
    except OSError as e:
        print(f"Error writing file: {e}", file=sys.stderr)
        sys.exit(1)
    if is_script_dir:
        output_path.chmod(0o755)
        print("✓ Made executable (755)")
        create_symlink(output_path)
    if content.strip():
        first_line = content.split("\n")[0]
        if first_line.startswith("#!"):
            print(f"\n📄 Shebang: {first_line}")


if __name__ == "__main__":
    raise SystemExit(main())
