#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
from pathlib import Path

import jsbeautifier


def beautify_json_file(path: str) -> bool | None:
    try:
        with Path(path).open(encoding="utf-8") as f:
            data = json.load(f)
        with Path(path).open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        return True
    except json.JSONDecodeError:
        return False
    except Exception:
        return False


def beautify_code_file(path: str, beautify_function, asset_type: str) -> bool | None:
    try:
        original_content = Path(path).read_text(encoding="utf-8")
        options = jsbeautifier.default_options()
        options.indent_size = 4
        beautified_content = beautify_function(original_content, options)
        Path(path).write_text(beautified_content, encoding="utf-8")
        return True
    except Exception:
        return False


def beautify_files_in_directory(cwd: Path | str = ".") -> None:
    processed_count = 0
    errors_count = 0
    beautifier_map = {
        ".js": (jsbeautifier.beautify, "JS"),
        ".html": (jsbeautifier.beautify, "HTML"),
        ".css": (jsbeautifier.beautify, "CSS"),
    }
    base_path = Path(cwd)
    for path in base_path.rglob("*"):
        if not path.is_file():
            continue
        filename = path.name
        if filename.endswith(".json"):
            success = beautify_json_file(str(path))
            if success:
                processed_count += 1
            else:
                errors_count += 1
        for ext, (func, asset_type) in beautifier_map.items():
            if filename.endswith(ext):
                success = beautify_code_file(str(path), func, asset_type)
                if success:
                    processed_count += 1
                else:
                    errors_count += 1
                break


if __name__ == "__main__":
    beautify_files_in_directory(Path.cwd())
