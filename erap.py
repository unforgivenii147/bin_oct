#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import subprocess
from multiprocessing import Pool
from pathlib import Path


def get_pyfiles_iter(root: Path):
    yield from root.rglob("*.py")


def runcmd(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = proc.stdout + proc.stderr
    return proc.returncode, combined


def run_tool(tool: str, path: Path) -> tuple[str, str | None]:
    try:
        if tool == "ty":
            cmd = ["ty", "check", str(path)]
        elif tool == "pyright":
            cmd = ["pyright", str(path)]
        elif tool == "pylint":
            cmd = ["pylint", "-E", str(path)]
        elif tool == "pyrefly":
            cmd = ["pyrefly", "check", str(path)]
        elif tool == "mypy":
            cmd = ["mypy", str(path)]
        else:
            return tool, None
        _returncode, output = runcmd(cmd)
        return tool, output if output.strip() else None
    except FileNotFoundError:
        return tool, f"ERROR: {tool} not found in PATH"
    except Exception as e:
        return tool, f"ERROR: {e!s}"


def append_tool_outputs(path: Path, outputs: dict[str, str | None]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write("\n\n")
        for tool, output in outputs.items():
            f.write(f"# ===== {tool} output =====\n")
            if output:
                for line in output.split("\n"):
                    if line.strip():
                        f.write(f"# {line}\n")
            else:
                f.write("# (no issues)\n")


def process_file(path: Path, tools: list[str]) -> str:
    outputs = {}
    for tool in tools:
        tool_name, output = run_tool(tool, path)
        outputs[tool_name] = output
    if (
        tools == ["ty"]
        and outputs.get("ty")
        and ("all checks passed" in outputs["ty"].lower())
    ) or (
        "error[unresolved-import]: Cannot resolve imported module `dh`"
        in outputs["ty"].lower()
    ):
        return f"✓ Skipped (ty: all checks passed): {path}"
    append_tool_outputs(path, outputs)
    return f"✓ Updated: {path}"


def collect_pyfiles(paths: list[str]):
    for path_str in paths:
        path = Path(path_str)
        if path.is_file() and path.suffix == ".py":
            yield path
        elif path.is_dir():
            yield from get_pyfiles_iter(path)


def main():
    parser = argparse.ArgumentParser(
        description="Run code checkers and append outputs to Python files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python script.py file.py
  python script.py . -a
  python script.py . -g -p
  python script.py dir/ -r
  python script.py file1.py file2.py -g -p
        """,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Python files or directories to process (default: . recursively)",
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Run all tools: ty, pyright, pylint, pyrefly",
    )
    parser.add_argument(
        "-g",
        "--pyright",
        action="store_true",
        help="Run pyright",
    )
    parser.add_argument(
        "-p",
        "--pylint",
        action="store_true",
        help="Run pylint",
    )
    parser.add_argument(
        "-r",
        "--pyrefly",
        action="store_true",
        help="Run pyrefly",
    )
    parser.add_argument(
        "-t",
        "--ty",
        action="store_true",
        help="Run ty",
    )
    parser.add_argument(
        "-m",
        "--mypy",
        action="store_true",
        help="Run mypy",
    )
    args = parser.parse_args()
    paths = args.paths if args.paths else ["."]
    enabled_tools = []
    if args.all:
        enabled_tools = ["ty", "pyright", "pylint", "pyrefly", "mypy"]
    else:
        if args.ty:
            enabled_tools.append("ty")
        if args.pyright:
            enabled_tools.append("pyright")
        if args.pylint:
            enabled_tools.append("pylint")
        if args.pyrefly:
            enabled_tools.append("pyrefly")
        if args.mypy:
            enabled_tools.append("mypy")
        if not enabled_tools:
            enabled_tools = ["ty", "pyright", "pyrefly"]
    files = list(collect_pyfiles(paths))
    if not files:
        print("No .py files found.")
        return
    with Pool(processes=4) as pool:
        async_results = [
            pool.apply_async(process_file, args=(f, enabled_tools)) for f in files
        ]
        for result in async_results:
            print(result.get())


if __name__ == "__main__":
    raise SystemExit(main())
