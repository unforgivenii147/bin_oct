#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def validate_lua_syntax(code: str) -> bool:
    try:
        result = subprocess.run(
            ["luac", "-p", "-"], input=code.encode(), capture_output=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        test_code = f"return (function() {code} end)()"
        result = subprocess.run(
            ["lua", "-e", test_code], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return basic_lua_validation(code)


def basic_lua_validation(code: str) -> bool:
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = []
    in_string = False
    string_char = None
    escape = False
    for _i, char in enumerate(code):
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char in ('"', "'"):
            if not in_string:
                in_string = True
                string_char = char
            elif char == string_char:
                in_string = False
                string_char = None
            continue
        if in_string:
            continue
        if char in pairs:
            stack.append(char)
        elif char in pairs.values():
            if not stack:
                return False
            last = stack.pop()
            if pairs[last] != char:
                return False
    return len(stack) == 0 and not in_string


def get_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        new_path = parent / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1


def extract_balanced_braces(text: str, start: int) -> tuple[int, int] | None:
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    string_char = None
    escape = False
    for i in range(start, len(text)):
        char = text[i]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char in ('"', "'"):
            if not in_string:
                in_string = True
                string_char = char
            elif char == string_char:
                in_string = False
                string_char = None
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return (start, i + 1)
    return None


def parse_plugin_name(block: str) -> str | None:
    patterns = [
        r'"([^"]+/[^"]+)"',
        r"'([^']+/[^']+)'",
        r'\[\s*"([^"]+/[^"]+)"\s*\]',
        r"\[\s*'([^']+/[^']+)'\s*\]",
    ]
    for pattern in patterns:
        match = re.search(pattern, block)
        if match:
            return match.group(1)
    match = re.search(r'["\']([a-zA-Z0-9_-]+/[a-zA-Z0-9._-]+)["\']', block)
    if match:
        return match.group(1)
    return None


def to_valid_filename(name: str) -> str:
    if "/" in name:
        name = name.split("/")[-1]
    name = name.removesuffix(".nvim")
    special_cases = {
        "nvim-lspconfig": "lsp",
        "nvim-treesitter": "treesitter",
        "nvim-cmp": "cmp",
        "nvim-lint": "lint",
        "nvim-dap": "dap",
        "nvim-dap-ui": "dap-ui",
        "nvim-dap-virtual-text": "dap-virtual-text",
        "nvim-dap-python": "dap-python",
        "nvim-surround": "surround",
        "nvim-autopairs": "autopairs",
        "nvim-colorizer": "colorizer",
        "nvim-notify": "notify",
        "nvim-bqf": "bqf",
        "nvim-illuminate": "illuminate",
    }
    return special_cases.get(name, name)


def format_lazyvim_spec(block: str, plugin_name: str) -> str:
    lines = block.strip().split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        cleaned.append(line)
    content = "\n".join(cleaned).strip()
    if not content.startswith("return"):
        if content.startswith("{"):
            content = f"return {content}"
        else:
            content = f"return {{\n  {content}\n}}"
    return content


def split_lua_plugins(input_path: str, move: bool = False) -> list[Path]:
    input_file = Path(input_path)
    if not input_file.exists():
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    content = input_file.read_text()
    start_idx = content.find("return")
    if start_idx == -1:
        start_idx = 0
    brace_start = content.find("{", start_idx)
    if brace_start == -1:
        print("Error: No table found in file", file=sys.stderr)
        sys.exit(1)
    bounds = extract_balanced_braces(content, brace_start)
    if not bounds:
        print("Error: Unbalanced braces in file", file=sys.stderr)
        sys.exit(1)
    _, outer_end = bounds
    inner_start = brace_start + 1
    inner_end = outer_end - 1
    inner_content = content[inner_start:inner_end]
    blocks = []
    i = 0
    while i < len(inner_content):
        char = inner_content[i]
        if char in " \t\n\r,":
            i += 1
            continue
        if char == "{":
            bounds = extract_balanced_braces(inner_content, i)
            if bounds:
                start, end = bounds
                block = inner_content[start:end].strip()
                blocks.append(block)
                i = end
                continue
        depth = 0
        j = i
        in_string = False
        string_char = None
        escape = False
        while j < len(inner_content):
            c = inner_content[j]
            if escape:
                escape = False
                j += 1
                continue
            if c == "\\":
                escape = True
                j += 1
                continue
            if c in ('"', "'"):
                if not in_string:
                    in_string = True
                    string_char = c
                elif c == string_char:
                    in_string = False
                    string_char = None
                j += 1
                continue
            if in_string:
                j += 1
                continue
            if c in "({[":
                depth += 1
            elif c in ")}]":
                depth -= 1
            elif c == "," and depth == 0:
                break
            j += 1
        i = j + 1 if j < len(inner_content) else len(inner_content)
    created_files = []
    valid_blocks = []
    for block in blocks:
        if not block.strip() or block.strip() == "{}":
            continue
        plugin_full = parse_plugin_name(block)
        if not plugin_full:
            print(
                f"Warning: Could not parse plugin name from block, skipping:\n{block[:100]}...",
                file=sys.stderr,
            )
            continue
        filename = to_valid_filename(plugin_full)
        target = Path(f"{filename}.lua")
        formatted = format_lazyvim_spec(block, plugin_full)
        if not validate_lua_syntax(formatted):
            print(
                f"Error: Invalid Lua syntax for {plugin_full}, skipping",
                file=sys.stderr,
            )
            print(f"Content:\n{formatted[:200]}...", file=sys.stderr)
            continue
        unique_target = get_unique_path(target)
        unique_target.write_text(formatted, encoding="utf-8")
        created_files.append(unique_target)
        valid_blocks.append(block)
        print(f"Created: {unique_target} <- {plugin_full}")
    if move and valid_blocks:
        backup = get_unique_path(input_file.with_suffix(input_file.suffix + ".bak"))
        input_file.rename(backup)
        input_file.write_text("return {\n}\n", encoding="utf-8")
        print(f"Replaced {input_file} with empty table (backup: {backup})")
    return created_files


def main():
    move = False
    input_path = None
    for arg in sys.argv[1:]:
        if arg == "-m":
            move = True
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}", file=sys.stderr)
            sys.exit(1)
        else:
            input_path = arg
    if not input_path:
        print("Usage: python split_plugins.py [-m] <input.lua>", file=sys.stderr)
        print(
            "  -m    Move/replace input file with empty table after extraction",
            file=sys.stderr,
        )
        sys.exit(1)
    created = split_lua_plugins(input_path, move)
    print(f"\nTotal files created: {len(created)}")


if __name__ == "__main__":
    main()
