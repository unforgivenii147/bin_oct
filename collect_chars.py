#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import mimetypes
import sys
from multiprocessing import Pool
from pathlib import Path

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".py",
    ".js",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".css",
    ".java",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".rs",
    ".go",
    ".rb",
    ".php",
    ".sh",
    ".bash",
    ".sql",
    ".pl",
    ".lua",
    ".ts",
    ".tsx",
    ".jsx",
    ".vue",
    ".scss",
    ".less",
    ".log",
    ".csv",
    ".tsv",
    ".ini",
    ".cfg",
    ".conf",
    ".properties",
    ".gradle",
    ".maven",
    ".cmake",
    ".makefile",
    ".dockerfile",
    ".gitignore",
    ".editorconfig",
    ".eslintrc",
    ".prettierrc",
}
BINARY_EXTENSIONS = {
    ".bin",
    ".exe",
    ".dll",
    ".so",
    ".o",
    ".a",
    ".zip",
    ".tar",
    ".gz",
    ".jpg",
    ".png",
    ".gif",
    ".ico",
    ".pdf",
    ".mp3",
    ".mp4",
    ".mov",
    ".avi",
    ".wmv",
    ".flv",
    ".mkv",
    ".webm",
    ".wav",
    ".flac",
}
SKIP_DIRS = {
    ".git",
    ".svn",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".env",
    ".egg-info",
    "dist",
    "build",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".tox",
    ".coverage",
    ".mypy_cache",
    "target",
    "out",
    "bin",
    ".gradle",
}


def is_text_file(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in BINARY_EXTENSIONS:
        return False
    if suffix in TEXT_EXTENSIONS:
        return True
    name = path.name.lower()
    if name in {
        "makefile",
        "dockerfile",
        "gemfile",
        "procfile",
        "rakefile",
        "guardfile",
        "capfile",
        "thorfile",
    }:
        return True
    if suffix == "":
        if name.startswith("."):
            return True
        try:
            with open(path, "rb") as f:
                chunk = f.read(8192)
                text_chars = sum(1 for b in chunk if 32 <= b < 127 or b in (9, 10, 13))
                return text_chars / len(chunk) > 0.75 if chunk else False
        except OSError:
            return False
    mime_type, _ = mimetypes.guess_type(str(path))
    if mime_type:
        return mime_type.startswith("text/")
    return False


def collect_chars_from_file(path: Path) -> set[str]:
    unique_chars = set()
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for chunk in iter(lambda: f.read(8192), ""):
                unique_chars.update(chunk)
    except OSError as e:
        print(f"Warning: Could not read {path}: {e}")
    return unique_chars


def process_file_task(args: tuple[Path, int]) -> tuple[set[str], int]:
    path, file_index = args
    chars = collect_chars_from_file(path)
    return (chars, file_index)


def get_text_files(root_dir: Path = Path(".")) -> list[Path]:
    text_files = []
    for item in root_dir.rglob("*"):
        if item.is_dir():
            if item.name in SKIP_DIRS:
                continue
            continue
        if item.is_symlink():
            continue
        if is_text_file(item):
            text_files.append(item)
    return sorted(text_files)


def main():
    root_dir = Path(".")
    output_file = Path("chars.txt")
    print(f"Scanning directory: {root_dir.resolve()}")
    print(f"Finding text-based files...")
    text_files = get_text_files(root_dir)
    if not text_files:
        print("No text files found!")
        sys.exit(0)
    print(f"Found {len(text_files):,} text files")
    print(f"\nProcessing files with 8 workers...")
    tasks = [(f, i) for i, f in enumerate(text_files)]
    all_chars = set()
    processed = 0
    with Pool(8) as pool:
        async_results = []
        for task in tasks:
            result = pool.apply_async(process_file_task, (task,))
            async_results.append(result)
        for i, async_result in enumerate(async_results):
            try:
                chars_set, _ = async_result.get(timeout=30)
                all_chars.update(chars_set)
                processed += 1
                if (i + 1) % 100 == 0:
                    print(
                        f"  Processed: {processed:,} files | Unique chars so far: {len(all_chars):,}"
                    )
            except Exception as e:
                print(f"  Error processing file: {e}")
    print(f"\n✓ Processed: {processed:,} files")
    print(f"✓ Unique characters found: {len(all_chars):,}")

    def sort_key(char):
        code = ord(char)
        if code < 32 and code not in (9, 10, 13):
            return (0, code)
        elif 32 <= code <= 126:
            return (1, code)
        elif code == 32:
            return (2, code)
        else:
            return (3, code)

    sorted_chars = sorted(all_chars, key=sort_key)
    print(f"Saving unique characters to {output_file}...")
    with open(output_file, "w", encoding="utf-8") as f:
        for char in sorted_chars:
            if char == "\n":
                f.write("\\n\n")
            elif char == "\r":
                f.write("\\r\n")
            elif char == "\t":
                f.write("\\t\n")
            elif char == " ":
                f.write("SPACE\n")
            elif ord(char) < 32:
                f.write(f"\\x{ord(char):02x}\n")
            else:
                f.write(f"{char}\n")
    print(f"✓ Saved to {output_file.resolve()}")
    print(f"\n📊 Statistics:")
    print(f"  Total unique characters: {len(all_chars)}")
    ascii_count = sum(1 for c in all_chars if ord(c) < 128)
    control_count = sum(1 for c in all_chars if ord(c) < 32)
    space_count = sum(1 for c in all_chars if c.isspace())
    digit_count = sum(1 for c in all_chars if c.isdigit())
    letter_count = sum(1 for c in all_chars if c.isalpha())
    unicode_count = len(all_chars) - ascii_count
    print(f"  ASCII characters: {ascii_count}")
    print(f"  Control characters: {control_count}")
    print(f"  Whitespace characters: {space_count}")
    print(f"  Digits: {digit_count}")
    print(f"  Letters: {letter_count}")
    print(f"  Unicode characters: {unicode_count}")
    print(f"\n📝 Sample characters (first 20):")
    for i, char in enumerate(sorted_chars[:20]):
        if char == "\n":
            display = "\\n (newline)"
        elif char == "\t":
            display = "\\t (tab)"
        elif char == "\r":
            display = "\\r (carriage return)"
        elif char == " ":
            display = "SPACE"
        elif ord(char) < 32:
            display = f"\\x{ord(char):02x} (control)"
        else:
            display = f"'{char}' (U+{ord(char):04X})"
        print(f"  {i + 1:2}. {display}")


if __name__ == "__main__":
    main()
