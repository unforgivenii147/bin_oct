#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import io
import sys
import tokenize
from pathlib import Path


def format_python_file(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    if not source.endswith("\n"):
        source += "\n"
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    output: list[str] = []
    indent_level = 0
    line_start = True

    def write(text: str) -> None:
        nonlocal line_start
        if line_start:
            output.append("    " * indent_level)
            line_start = False
        output.append(text)

    def newline() -> None:
        nonlocal line_start
        while output and output[-1].endswith(" "):
            output.pop()
        if not output or not output[-1].endswith("\n"):
            output.append("\n")
        line_start = True

    previous_type = None
    for token in tokens:
        token_type = token.type
        token_string = token.string
        if token_type in {
            tokenize.ENCODING,
            tokenize.ENDMARKER,
            tokenize.NL,
        }:
            continue
        if token_type == tokenize.INDENT:
            indent_level += 1
            continue
        if token_type == tokenize.DEDENT:
            indent_level = max(0, indent_level - 1)
            continue
        if token_type == tokenize.NEWLINE:
            newline()
            previous_type = token_type
            continue
        if token_type == tokenize.COMMENT:
            if not line_start:
                output.append(" ")
            write(token_string)
            newline()
            previous_type = token_type
            continue
        if token_string == ":":
            write(":")
            newline()
            previous_type = token_type
            continue
        if (
            not line_start
            and previous_type
            in {
                tokenize.NAME,
                tokenize.NUMBER,
                tokenize.STRING,
            }
            and token_type
            in {
                tokenize.NAME,
                tokenize.NUMBER,
                tokenize.STRING,
            }
        ):
            output.append(" ")
        if token_string in {
            "=",
            "+",
            "-",
            "*",
            "/",
            "%",
            "==",
            "!=",
            "<",
            ">",
            "<=",
            ">=",
        }:
            if output and not output[-1].endswith((" ", "\n")):
                output.append(" ")
            write(token_string)
            output.append(" ")
        else:
            write(token_string)
        previous_type = token_type
    formatted = "".join(output).rstrip() + "\n"
    path.write_text(formatted, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {Path(sys.argv[0]).name} FILE.py", file=sys.stderr)
        raise SystemExit(2)
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"Error: file not found: {path}", file=sys.stderr)
        raise SystemExit(1)
    try:
        format_python_file(path)
    except (SyntaxError, tokenize.TokenError) as error:
        print(f"Error: input is not valid tokenizable Python: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
