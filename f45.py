#!/data/data/com.termux/files/home/.local/bin/python
import argparse
import shutil
import sys
import textwrap
from pathlib import Path


def wrap_text_content(content: str, width: int) -> str:
    """Wraps text content to target width while preserving paragraph structures."""
    paragraphs = content.split("\n\n")
    wrapped_paragraphs = []

    for paragraph in paragraphs:
        lines = paragraph.splitlines()
        if not lines:
            wrapped_paragraphs.append("")
            continue

        # Process lines within paragraph
        wrapped_lines = []
        for line in lines:
            if not line.strip():
                wrapped_lines.append("")
                continue

            # Wrap individual line respecting word boundaries
            wrapped = textwrap.fill(
                line,
                width=width,
                break_long_words=False,
                break_on_hyphens=False,
                replace_whitespace=False,
                drop_whitespace=True,
            )
            wrapped_lines.append(wrapped)

        wrapped_paragraphs.append("\n".join(wrapped_lines))

    return "\n\n".join(wrapped_paragraphs)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wrap text file content to match terminal width."
    )
    parser.add_argument("file", type=Path, help="Path to the target file")
    parser.add_argument(
        "-i",
        "--inplace",
        action="store_true",
        help="Modify the original file in-place",
    )
    parser.add_argument(
        "-w",
        "--width",
        type=int,
        default=None,
        help="Override target wrapping width (defaults to current terminal width)",
    )

    args = parser.parse_args()
    file_path: Path = args.file

    if not file_path.exists():
        print(f"Error: File '{file_path}' not found.", file=sys.stderr)
        sys.exit(1)
    if file_path.is_dir():
        print(f"Error: '{file_path}' is a directory.", file=sys.stderr)
        sys.exit(1)

    # Determine wrapping width
    if args.width:
        width = max(args.width, 20)
    else:
        columns = shutil.get_terminal_size().columns
        width = max(columns, 20)

    # Read content
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        sys.exit(1)

    # Perform wrapping
    wrapped_content = wrap_text_content(content, width)

    # Determine target output path
    if args.inplace:
        output_path = file_path
    else:
        output_path = file_path.with_name(f"{file_path.stem}_wrapped{file_path.suffix}")

    # Write output
    try:
        output_path.write_text(wrapped_content + "\n", encoding="utf-8")
        print(f"Successfully wrote wrapped text ({width} cols) to '{output_path}'.")
    except Exception as e:
        print(f"Error writing file: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
