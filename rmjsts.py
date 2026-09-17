#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def remove_js_comments(content: str) -> str:
    result = []
    i = 0
    in_string = False
    string_char = None
    while i < len(content):
        if content[i] in ('"', "'", "`") and (i == 0 or content[i - 1] != "\\"):
            if not in_string:
                in_string = True
                string_char = content[i]
                result.append(content[i])
                i += 1
            elif content[i] == string_char:
                in_string = False
                string_char = None
                result.append(content[i])
                i += 1
            else:
                result.append(content[i])
                i += 1
        elif in_string:
            result.append(content[i])
            i += 1
        elif i + 1 < len(content) and content[i : i + 2] == "//":
            while i < len(content) and content[i] != "\n":
                i += 1
            if i < len(content):
                result.append("\n")
                i += 1
        elif i + 1 < len(content) and content[i : i + 2] == "/*":
            i += 2
            while i + 1 < len(content):
                if content[i : i + 2] == "*/":
                    i += 2
                    break
                if content[i] == "\n":
                    result.append("\n")
                i += 1
        else:
            result.append(content[i])
            i += 1
    return "".join(result)


def process_file(path: Path) -> str | None:
    try:
        content = path.read_text(encoding="utf-8")
        cleaned = remove_js_comments(content)
        path.write_text(cleaned, encoding="utf-8")
        return None
    except Exception as e:
        return f"Error processing {path}: {e}"


def main():
    if len(sys.argv) > 1:
        paths = [Path(arg) for arg in sys.argv[1:]]
    else:
        paths = [Path.cwd()]
    files_to_process = []
    for path in paths:
        if path.is_file():
            if path.suffix in (".js", ".ts", ".jsx", ".tsx"):
                files_to_process.append(path)
        elif path.is_dir():
            for ext in ("*.js", "*.ts", "*.jsx", "*.tsx"):
                files_to_process.extend(path.rglob(ext))
    with ThreadPoolExecutor() as executor:
        results = executor.map(process_file, files_to_process)
    errors = [e for e in results if e]
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        sys.exit(1)
    print(f"Processed {len(files_to_process)} file(s)")


if __name__ == "__main__":
    raise SystemExit(main())
