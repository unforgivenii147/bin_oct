#!/data/data/com.termux/files/home/.local/bin/python
import sys
import tempfile
import unicodedata
from pathlib import Path


def normalize_line(line: str) -> str:
    text = unicodedata.normalize("NFKC", line)
    text = "".join(char for char in text if char.isprintable())
    text = "".join(
        char for char in text if not unicodedata.category(char).startswith("P")
    )
    text = text.casefold()
    text = "_".join(text.split())
    return text


def normalize_file_in_place(path: Path) -> None:
    with (
        path.open("r", encoding="utf-8", newline="") as source,
        tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary,
    ):
        temporary_path = Path(temporary.name)
        for line in source:
            content = line.rstrip("\r\n")
            temporary.write(normalize_line(content) + "\n")
    temporary_path.replace(path)


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {Path(sys.argv[0]).name} INPUT_FILE", file=sys.stderr)
        raise SystemExit(2)
    input_path = Path(sys.argv[1])
    if not input_path.is_file():
        print(f"Error: not a file: {input_path}", file=sys.stderr)
        raise SystemExit(1)
    try:
        normalize_file_in_place(input_path)
    except UnicodeDecodeError:
        print(
            f"Error: {input_path} is not valid UTF-8.",
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
