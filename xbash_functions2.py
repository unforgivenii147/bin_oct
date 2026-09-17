#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import contextlib
import os
import re
import sys
from collections.abc import Generator
from pathlib import Path

IS_TERMUX = os.environ.get(
    "TERMUX_VERSION"
) is not None or "com.termux" in os.environ.get("PREFIX", "")
EXCLUDED = {
    ".py",
    ".h",
    ".c",
    ".js",
    ".ts",
    ".hpp",
    ".cpp",
    ".pyx",
    ".jsx",
    ".lua",
    ".tsx",
    ".pl",
    ".am",
    ".pm",
    ".so",
    ".rmeta",
    ".syntax",
}


class ShellScriptFinder:
    def __init__(self, include_extensionless: bool = True, skip_hidden: bool = False):
        self.include_extensionless = include_extensionless
        self.skip_hidden = skip_hidden
        self.script_count = 0

    def is_bash_script(self, path: Path) -> bool:
        if not path.is_file():
            return False
        if self.skip_hidden and path.name.startswith("."):
            return False
        if path.suffix == ".sh":
            return True
        if not self.include_extensionless:
            return False
        try:
            if path.stat().st_size > 1000000:
                return False
        except OSError:
            return False
        try:
            with open(path, "rb") as f:
                first_bytes = f.read(2)
                if b"\x00" in first_bytes:
                    return False
                f.seek(0)
                first_line = f.readline().decode("utf-8", errors="ignore").strip()
                if first_line.startswith("#!"):
                    shell_patterns = [
                        "bash",
                        "sh",
                        "dash",
                        "ksh",
                        "zsh",
                        "ash",
                        "shell",
                    ]
                    shebang_lower = first_line.lower()
                    if any(shell in shebang_lower for shell in shell_patterns):
                        return True
        except (OSError, UnicodeDecodeError):
            return False
        return False

    def walk_directory(self, directory: Path) -> Generator[Path, None, None]:
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    if entry.is_file():
                        if path.suffix in EXCLUDED:
                            continue
                        if self.is_bash_script(path):
                            self.script_count += 1
                            yield path.resolve()
                    elif entry.is_dir():
                        if self.skip_hidden and path.name.startswith("."):
                            continue
                        yield from self.walk_directory(path)
        except PermissionError:
            print(f"Warning: Permission denied accessing {directory}", file=sys.stderr)
        except OSError as e:
            print(f"Warning: OS error accessing {directory}: {e}", file=sys.stderr)

    def find_scripts(self, paths: list[Path]) -> Generator[Path, None, None]:
        for path in paths:
            if not path.exists():
                print(f"Warning: {path} does not exist, skipping...", file=sys.stderr)
                continue
            if path.is_file():
                if self.is_bash_script(path):
                    self.script_count += 1
                    yield path.resolve()
            elif path.is_dir():
                yield from self.walk_directory(path)
            else:
                print(
                    f"Warning: {path} is not a file or directory, skipping...",
                    file=sys.stderr,
                )


class FunctionExtractor:
    def __init__(self):
        self.function_count = 0

    def extract_functions(
        self, sh_file: Path
    ) -> Generator[tuple[str, str], None, None]:
        try:
            with open(sh_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading {sh_file}: {e}", file=sys.stderr)
            return
        lines = content.split("\n")
        function_start_pattern = re.compile(
            "^\\s*(?:function\\s+)?(\\w[\\w\\-]*)\\s*(?:\\(\\))?\\s*\\{"
        )
        i = 0
        while i < len(lines):
            line = lines[i]
            match = function_start_pattern.match(line)
            if match:
                func_name = match.group(1)
                func_lines = [line]
                brace_count = line.count("{") - line.count("}")
                j = i + 1
                while j < len(lines) and brace_count > 0:
                    current_line = lines[j]
                    func_lines.append(current_line)
                    brace_count += current_line.count("{") - current_line.count("}")
                    j += 1
                if brace_count == 0:
                    function_content = "\n".join(func_lines)
                    self.function_count += 1
                    yield (func_name, function_content)
                else:
                    print(
                        f"Warning: Could not find matching closing brace for function '{func_name}' in {sh_file}",
                        file=sys.stderr,
                    )
                i = j
            else:
                i += 1


class FunctionWriter:
    def __init__(self, output_dir: Path, use_extension: bool = True):
        self.output_dir = output_dir
        self.use_extension = use_extension
        self.written_count = 0

    def write_function(
        self, func_name: str, func_content: str, source_file: Path
    ) -> Path | None:
        safe_func_name = re.sub("[^\\w\\-]", "_", func_name)
        try:
            rel_path = source_file.relative_to(Path.cwd())
        except ValueError:
            rel_path = source_file
        func_output_dir = self.output_dir / rel_path.parent
        if self.use_extension:
            output_file = func_output_dir / f"{safe_func_name}.sh"
        else:
            output_file = func_output_dir / safe_func_name
        func_output_dir.mkdir(parents=True, exist_ok=True)
        header = f"#!/bin/bash\n# Function: {func_name}\n# Extracted from: {
            source_file
        }\n# Original file: {source_file.name}\n# Environment: {
            ('Termux' if IS_TERMUX else 'Standard')
        }\n\n"
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(header)
                f.write(func_content)
                f.write("\n")
            with contextlib.suppress(OSError):
                output_file.chmod(output_file.stat().st_mode | 73)
            self.written_count += 1
            return output_file
        except Exception as e:
            print(
                f"Error writing function '{func_name}' to {output_file}: {e}",
                file=sys.stderr,
            )
            return None


def process_paths(
    input_paths: list[Path],
    output_dir: Path,
    include_extensionless: bool = True,
    use_extension: bool = True,
    skip_hidden: bool = False,
    verbose: bool = False,
) -> tuple[int, int]:
    finder = ShellScriptFinder(include_extensionless, skip_hidden)
    extractor = FunctionExtractor()
    writer = FunctionWriter(output_dir, use_extension)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        print(
            f"Error: Cannot create output directory '{output_dir}'. Check permissions.",
            file=sys.stderr,
        )
        return (0, 0)
    files_processed = 0
    print("Processing files using generator pattern...")
    for script_file in finder.find_scripts(input_paths):
        files_processed += 1
        if verbose:
            print(f"  Processing: {script_file}")
        for func_name, func_content in extractor.extract_functions(script_file):
            output_path = writer.write_function(func_name, func_content, script_file)
            if output_path and verbose:
                print(f"    -> Extracted: {func_name} -> {output_path.name}")
    return (files_processed, extractor.function_count)


def main():
    parser = argparse.ArgumentParser(
        description="Extract functions from shell scripts using generator-style filesystem walker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n  # Process all shell scripts in current directory recursively\n  %(prog)s\n  \n  # Process specific files and directories\n  %(prog)s script1.sh myscript dir1/ dir2/\n  \n  # Specify output directory\n  %(prog)s -o extracted_functions dir1/ dir2/\n  \n  # Only process .sh files (ignore extensionless scripts)\n  %(prog)s --sh-only\n  \n  # Skip hidden files and directories\n  %(prog)s --skip-hidden\n  \n  # Verbose output\n  %(prog)s --verbose\n\nGenerator Benefits:\n  - Memory efficient: only processes one file at a time\n  - Lazy evaluation: doesn't load all files into memory\n  - Ideal for large directory trees and Termux environments\n  - Uses os.scandir() for efficient filesystem walking\n        ",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="Files and/or directories to process. If none provided, processes all shell scripts in current directory recursively.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("extracted_functions"),
        help="Output directory for extracted functions (default: extracted_functions)",
    )
    parser.add_argument(
        "--sh-only",
        action="store_true",
        help="Only process files with .sh extension (ignore extensionless scripts)",
    )
    parser.add_argument(
        "--no-extension",
        action="store_true",
        help="Output functions without .sh extension",
    )
    parser.add_argument(
        "--skip-hidden",
        action="store_true",
        help="Skip hidden files and directories (starting with .)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show verbose output including each processed file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only find and list scripts without extracting functions",
    )
    args = parser.parse_args()
    if IS_TERMUX:
        print("Running in Termux environment (optimized for mobile)")
    if args.inputs:
        input_paths = args.inputs
    else:
        input_paths = [Path(".")]
    include_extensionless = not args.sh_only
    if args.dry_run:
        print("Searching for shell scripts...")
        finder = ShellScriptFinder(include_extensionless, args.skip_hidden)
        scripts = list(finder.find_scripts(input_paths))
        print(f"\nFound {len(scripts)} shell script(s):")
        for script in scripts:
            print(f"  {script}")
        print(f"\nWould extract functions to: {args.output.absolute()}")
        return 0
    print("Searching for shell scripts...")
    files_processed, functions_extracted = process_paths(
        input_paths=input_paths,
        output_dir=args.output,
        include_extensionless=include_extensionless,
        use_extension=not args.no_extension,
        skip_hidden=args.skip_hidden,
        verbose=args.verbose,
    )
    print("\nDone!")
    print(f"  Files processed: {files_processed}")
    print(f"  Functions extracted: {functions_extracted}")
    print(f"  Output directory: {args.output.absolute()}")
    if IS_TERMUX:
        with contextlib.suppress(BaseException):
            args.output.chmod(args.output.stat().st_mode | 493)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting...")
        sys.exit(1)
