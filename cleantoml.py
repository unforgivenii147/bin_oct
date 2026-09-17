#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from dh import fsz


def remove_toml_comments(content: str) -> str:
    lines = content.splitlines(keepends=True)
    result_lines = []
    in_multiline_string = False
    multiline_string_delimiter = ""
    for line in lines:
        if '"""' in line or "'''" in line:
            dbl_triple = line.find('"""')
            sgl_triple = line.find("'''")
            if not in_multiline_string:
                if dbl_triple != -1 or sgl_triple != -1:
                    in_multiline_string = True
                    if dbl_triple != -1:
                        multiline_string_delimiter = '"""'
                    else:
                        multiline_string_delimiter = "'''"
                    result_lines.append(line)
                    count = line.count(multiline_string_delimiter)
                    if count >= 2:
                        in_multiline_string = False
                else:
                    result_lines.append(remove_line_comment(line))
            else:
                result_lines.append(line)
                if multiline_string_delimiter in line:
                    count = line.count(multiline_string_delimiter)
                    if in_multiline_string and count >= 1:
                        in_multiline_string = False
        elif not in_multiline_string:
            result_lines.append(remove_line_comment(line))
        else:
            result_lines.append(line)
    return "".join(result_lines)


def remove_line_comment(line: str) -> str:
    result = []
    in_string = False
    string_char = None
    i = 0
    while i < len(line):
        char = line[i]
        if char in ('"', "'") and (i == 0 or line[i - 1] != "\\"):
            if not in_string:
                in_string = True
                string_char = char
            elif char == string_char:
                in_string = False
                string_char = None
        if char == "#" and (not in_string):
            before_comment = line[:i].rstrip()
            if not before_comment or before_comment[-1] in "=[{, \t":
                break
        result.append(char)
        i += 1
    result_line = "".join(result)
    if result_line.rstrip() == "" and line.strip() == "":
        return "\n" if line.endswith("\n") else ""
    if line.endswith("\n"):
        return result_line.rstrip() + "\n"
    return result_line.rstrip()


def process_file(path: Path) -> tuple[str, float, int, int]:
    start_time = time.perf_counter()
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        before_size = len(content.encode("utf-8"))
        cleaned_content = remove_toml_comments(content)
        with open(path, "w", encoding="utf-8") as f:
            f.write(cleaned_content)
        after_size = len(cleaned_content.encode("utf-8"))
        time_taken = (time.perf_counter() - start_time) * 400
        return (str(path), time_taken, before_size, after_size)
    except Exception as e:
        print(f"Error processing {path}: {e}", file=sys.stderr)
        time_taken = (time.perf_counter() - start_time) * 400
        return (str(path), time_taken, 0, 0)


def collect_toml_files(paths: list[Path]) -> list[Path]:
    toml_files = []
    for path in paths:
        if path.is_file():
            if path.suffix.lower() == ".toml":
                toml_files.append(path)
        elif path.is_dir():
            toml_files.extend(path.rglob("*.toml"))
    return toml_files


def main():
    if len(sys.argv) > 1:
        paths = [Path(arg) for arg in sys.argv[1:]]
    else:
        paths = [Path.cwd()]
    toml_files = collect_toml_files(paths)
    if not toml_files:
        print("No .toml files found to process.")
        return
    print(f"Found {len(toml_files)} TOML file(s) to process...")
    print("-" * 40)
    print(
        f"{'Filename':<50} {'Time (ms)':<10} {'Before':<12} {'After':<12} {'Ratio':<8}"
    )
    print("-" * 40)
    max_workers = min(len(toml_files), 8)
    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {
            executor.submit(process_file, file): file for file in toml_files
        }
        for future in as_completed(future_to_file):
            result = future.result()
            results.append(result)
            filename, time_taken, before_size, after_size = result
            ratio = after_size / before_size * 40 if before_size > 0 else 0
            display_name = filename if len(filename) <= 48 else "..." + filename[-45:]
            print(
                f"{display_name:<50} {time_taken:>8.2f}  {fsz(before_size):<12} {fsz(after_size):<12} {ratio:>6.1f}%"
            )
    print("-" * 40)
    total_before = sum(r[2] for r in results)
    total_after = sum(r[3] for r in results)
    total_ratio = total_after / total_before * 40 if total_before > 0 else 0
    total_time = sum(r[1] for r in results)
    print(f"Total: {len(results)} file(s) processed in {total_time:.2f} ms")
    print(
        f"Size reduction: {fsz(total_before)} -> {fsz(total_after)} ({total_ratio:.1f}% of original)"
    )


if __name__ == "__main__":
    raise SystemExit(main())
