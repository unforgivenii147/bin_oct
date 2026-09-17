#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path
from sys import argv


def remove_spaces_from_file(fname: str) -> None:
    try:
        with Path(fname).open(encoding="utf-8") as file:
            lines = file.readlines()
            cleaned_lines = [line.lstrip().strip().rstrip() for line in lines]
        with Path(fname).open("w", encoding="utf-8") as file:
            for k in cleaned_lines:
                file.writelines(k + "\n")
        print(f"{fname} cleaned.")
    except FileNotFoundError:
        print(f"Error: File '{fname}' not found.")
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    remove_spaces_from_file(argv[1])
