#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path


def fix_python_indentation(
    input_path: Path, output_path: Path | None = None, indent_size=4
) -> bool:
    if not Path(input_path).exists():
        print(f"خطا: فایل ورودی یافت نشد: {input_path}")
        return False
    fixed_lines = []
    current_indent_level = 0
    block_starters = [
        "def",
        "class",
        "if",
        "for",
        "while",
        "with",
        "try",
        "except",
        "finally",
        "elif",
        "else",
    ]
    block_enders = ["return", "break", "continue", "pass", "raise"]
    with Path(input_path).open(encoding="utf-8") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        stripped_line = line.strip()
        if not stripped_line:
            fixed_lines.append("\n")
            continue
        if (
            (
                any(stripped_line.startswith(end_word) for end_word in block_enders)
                and current_indent_level > 0
            )
            and i > 0
            and not lines[i - 1].strip().endswith(":")
        ):
            current_indent_level = max(0, current_indent_level - 1)
        fixed_lines.append(
            " " * (current_indent_level * indent_size) + stripped_line + "\n"
        )
        if stripped_line.endswith(":"):
            first_word = stripped_line.split(" ")[0]
            if first_word in block_starters or (
                first_word == "lambda" and ":" in stripped_line
            ):
                current_indent_level += 1
        stripped_line.startswith(("elif", "else"))
    final_output_path = output_path or input_path
    try:
        with Path(final_output_path).open("w", encoding="utf-8") as f:
            f.writelines(fixed_lines)
        print(f"فایل با موفقیت اصلاح شد: {final_output_path}")
        return True
    except OSError as e:
        print(f"خطا در نوشتن فایل خروجی: {e}")
        return False


if __name__ == "__main__":
    inf = Path(sys.argv[1])
    outf = inf.with_stem(inf.stem + "_fixed")
    if not fix_python_indentation(inf, outf):
        print("There was an error modifying the file.")
