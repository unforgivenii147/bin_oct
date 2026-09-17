#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import io
import re
import sys
import tokenize
from pathlib import Path

HEREDOC_START = re.compile(
    r"""
    \bpython(?:3(?:\.\d+)?)?      # python, python3, python3.12, etc.
    \s+
    (?:
        [^\n]*?                  # optional flags, such as -u
        \s+
    )?
    -\s*<<-?\s*                  # stdin marker and heredoc operator
    (?P<quote>['"]?)             # optional quote around delimiter
    (?P<tag>[A-Za-z_][A-Za-z0-9_]*)
    (?P=quote)
    """,
    re.VERBOSE,
)


def extract_heredoc(source: str) -> tuple[str, str]:
    match = HEREDOC_START.search(source)
    if match is None:
        raise ValueError(
            "No Python heredoc was found. Expected syntax like: python - <<'PY' ... PY"
        )
    tag = match.group("tag")
    content_start = match.end()
    normal_end = re.compile(rf"(?:^|\n)[ \t]*{re.escape(tag)}[ \t]*(?=\n|$)").search(
        source, content_start
    )
    if normal_end is not None:
        python_code = source[content_start : normal_end.start()]
        return python_code.strip(), tag
    flattened_end = list(
        re.finditer(rf"(?:^|\s){re.escape(tag)}(?:\s|$)", source[content_start:])
    )
    if not flattened_end:
        raise ValueError(f"Closing heredoc delimiter {tag!r} was not found.")
    end_match = flattened_end[-1]
    python_code = source[content_start : content_start + end_match.start()]
    return python_code.strip(), tag


def add_line_breaks(code: str) -> str:
    if not code.endswith("\n"):
        code += "\n"
    tokens = list(tokenize.generate_tokens(io.StringIO(code).readline))
    result: list[str] = []
    indent_level = 0
    at_line_start = True
    paren_depth = 0
    previous: tokenize.TokenInfo | None = None

    def append(text: str) -> None:
        nonlocal at_line_start
        if at_line_start:
            result.append("    " * indent_level)
            at_line_start = False
        result.append(text)

    def add_space() -> None:
        if result and not result[-1].endswith((" ", "\n")):
            result.append(" ")

    def newline() -> None:
        nonlocal at_line_start
        while result and result[-1] == " ":
            result.pop()
        if result and not result[-1].endswith("\n"):
            result.append("\n")
        at_line_start = True

    for index, token in enumerate(tokens):
        token_type = token.type
        text = token.string
        if token_type in {
            tokenize.ENCODING,
            tokenize.ENDMARKER,
            tokenize.NL,
        }:
            continue
        if token_type == tokenize.NEWLINE:
            newline()
            previous = token
            continue
        if token_type == tokenize.INDENT:
            indent_level += 1
            continue
        if token_type == tokenize.DEDENT:
            indent_level = max(0, indent_level - 1)
            continue
        if token_type == tokenize.COMMENT:
            if not at_line_start:
                add_space()
            append(text)
            newline()
            previous = token
            continue
        if text in {"(", "[", "{"}:
            append(text)
            paren_depth += 1
            previous = token
            continue
        if text in {")", "]", "}"}:
            append(text)
            paren_depth = max(0, paren_depth - 1)
            previous = token
            continue
        if text == ",":
            append(",")
            add_space()
            previous = token
            continue
        if text == ";":
            newline()
            previous = token
            continue
        if text == ":" and paren_depth == 0:
            append(":")
            newline()
            indent_level += 1
            previous = token
            continue
        if (
            token_type == tokenize.NAME
            and previous is not None
            and paren_depth == 0
            and previous.string in {")", "]", "}", '"', "'"}
            and text
            in {
                "import",
                "from",
                "for",
                "while",
                "if",
                "elif",
                "else",
                "try",
                "except",
                "finally",
                "with",
                "def",
                "class",
                "return",
                "raise",
                "print",
            }
        ):
            newline()
        if (
            previous is not None
            and previous.type in {tokenize.NAME, tokenize.NUMBER, tokenize.STRING}
            and token_type in {tokenize.NAME, tokenize.NUMBER, tokenize.STRING}
        ):
            add_space()
        if text in {
            "=",
            "+=",
            "-=",
            "*=",
            "/=",
            "//=",
            "%=",
            "==",
            "!=",
            "<",
            ">",
            "<=",
            ">=",
            "+",
            "-",
            "*",
            "/",
            "//",
            "%",
            "|",
            "&",
            "^",
        }:
            add_space()
            append(text)
            add_space()
        else:
            append(text)
        previous = token
    return "".join(result).rstrip() + "\n"


def output_path_for(input_path: Path) -> Path:
    stem = input_path.stem or "extracted"
    output = Path.cwd() / f"{stem}_extracted.py"
    number = 2
    while output.exists():
        output = Path.cwd() / f"{stem}_extracted_{number}.py"
        number += 1
    return output


def main() -> None:
    if len(sys.argv) != 2:
        program = Path(sys.argv[0]).name
        print(f"Usage: {program} INPUT_FILE", file=sys.stderr)
        raise SystemExit(2)
    input_path = Path(sys.argv[1]).expanduser()
    if not input_path.is_file():
        print(f"Error: not a file: {input_path}", file=sys.stderr)
        raise SystemExit(1)
    try:
        shell_source = input_path.read_text(encoding="utf-8")
        python_code, tag = extract_heredoc(shell_source)
        formatted_code = add_line_breaks(python_code)
    except (OSError, ValueError, SyntaxError, tokenize.TokenError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
    output_path = output_path_for(input_path)
    output_path.write_text(formatted_code, encoding="utf-8")
    print(f"Extracted heredoc {tag!r} to: {output_path}")


if __name__ == "__main__":
    main()
