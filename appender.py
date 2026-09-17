#!/data/data/com.termux/files/home/.local/bin/python
from pathlib import Path
import sys


if __name__ == "__main__":
    fn = Path.home() / "prompt.txt"  # (sys.argv[1])
    text = fn.read_text(encoding="utf-8")

    for py_file in Path.cwd().glob("*.txt"):
        try:
            py_file.write_text(
                py_file.read_text(encoding="utf-8") + text, encoding="utf-8"
            )
            print(f"✓ Updated: {py_file.name}")
        except Exception as e:
            print(f"✗ Error: {py_file.name} - {e}")
