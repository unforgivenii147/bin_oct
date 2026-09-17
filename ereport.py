#!/data/data/com.termux/files/home/.local/bin/python
import json
import shutil
import subprocess
from pathlib import Path

# Tool command configurations
TOOLS = {
    "mypy": ["mypy", "--ignore-missing-imports"],
    "ruff": ["ruff", "check", "--fix", "--unsafe-fixes"],
    "ty": ["ty", "check"],
    "pyrefly": ["pyrefly", "check"],
    "pylint": ["pylint", "--errors-only"],
}


def execute_tool(cmd_base: list[str], target_file: Path) -> dict:
    """Runs a single tool command against target file and returns output details."""
    tool_name = cmd_base[0]

    if shutil.which(tool_name) is None:
        return {
            "status": "skipped",
            "error": f"Executable '{tool_name}' not found in PATH.",
        }

    cmd = cmd_base + [str(target_file)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        combined_output = (proc.stdout + proc.stderr).strip()
        return {
            "exit_code": proc.returncode,
            "has_errors": proc.returncode != 0,
            "output": combined_output if combined_output else "No output.",
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
        }


def analyze_file(py_file: Path, report_dir: Path) -> None:
    """Runs all checks on a Python file and writes its report JSON."""
    print(f"Processing: {py_file.name}")
    report_data = {
        "filename": py_file.name,
        "filepath": str(py_file.resolve()),
        "tools": {},
    }

    for tool_name, cmd_base in TOOLS.items():
        report_data["tools"][tool_name] = execute_tool(cmd_base, py_file)

    # Output JSON path: report/<filename_stem>.json (e.g., report/fn.json)
    output_json = report_dir / f"{py_file.stem}.json"
    output_json.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    print(f"  -> Report saved: {output_json}")


def main() -> None:
    current_dir = Path.cwd()
    report_dir = current_dir / "report"
    report_dir.mkdir(exist_ok=True)

    # Script filename to avoid self-analysis
    script_name = Path(__file__).name

    # Find all .py files directly inside current directory
    py_files = sorted(
        [
            f
            for f in current_dir.iterdir()
            if f.is_file() and f.suffix == ".py" and f.name != script_name
        ]
    )

    if not py_files:
        print("No .py files found in current directory.")
        return

    print(
        f"Found {len(py_files)} Python file(s). Generating reports in '{report_dir.name}/'...\n"
    )
    for py_file in py_files:
        analyze_file(py_file, report_dir)

    print("\nCompleted analysis for all files.")


if __name__ == "__main__":
    main()
