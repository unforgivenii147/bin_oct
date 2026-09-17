#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def extract_plugin_name(plugin_block):
    match = re.search(r'"([^"]+)"', plugin_block)
    if match:
        plugin_url = match.group(1)
        plugin_name = plugin_url.split("/")[-1]
        plugin_name = re.sub(r"[^a-zA-Z0-9\-_.]", "_", plugin_name)
        return plugin_name
    return None


def parse_lua_file(content):
    content = content.strip()
    if content.startswith("return"):
        content = content[6:].strip()
    content = content.removeprefix("{")
    content = content.removesuffix("}")
    plugins = []
    current_plugin = []
    brace_count = 0
    in_string = False
    string_char = None
    for i, char in enumerate(content):
        if char in ('"', "'") and (i == 0 or content[i - 1] != "\\"):
            if not in_string:
                in_string = True
                string_char = char
            elif char == string_char:
                in_string = False
        if not in_string:
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    current_plugin.append(char)
                    plugin_text = "".join(current_plugin).strip()
                    if plugin_text:
                        plugin_text = plugin_text.removesuffix(",")
                        plugins.append(plugin_text)
                    current_plugin = []
                    continue
        if brace_count > 0:
            current_plugin.append(char)
    return plugins


def create_plugin_file(plugin_name, plugin_content, output_dir):
    filename = f"{plugin_name}.lua"
    path = os.path.join(output_dir, filename)
    file_content = f"""return {plugin_content}
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(file_content)
    return path


def main():
    if len(sys.argv) < 2:
        print("Usage: python split_plugins.py <input_file.lua> [output_directory]")
        print(
            "       or: cat plugins.lua | python split_plugins.py - [output_directory]"
        )
        sys.exit(1)
    input_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "plugins"
    if input_file == "-":
        content = sys.stdin.read()
    else:
        with open(input_file, "r", encoding="utf-8") as f:
            content = f.read()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    plugins = parse_lua_file(content)
    if not plugins:
        print("No plugins found in the input file.")
        sys.exit(1)
    print(f"Found {len(plugins)} plugin specifications.")
    for i, plugin_content in enumerate(plugins, 1):
        plugin_name = extract_plugin_name(plugin_content)
        if plugin_name:
            path = create_plugin_file(plugin_name, plugin_content, output_dir)
            print(f"[{i}/{len(plugins)}] Created: {path}")
        else:
            print(
                f"[{i}/{len(plugins)}] Warning: Could not extract plugin name, skipping..."
            )
    Path(input_file).unlink()
    print(f"\n ********************\n {input_file} removed. look in '{output_dir}' ")


if __name__ == "__main__":
    main()
