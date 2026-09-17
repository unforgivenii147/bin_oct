#!/data/data/com.termux/files/home/.local/bin/python
import re
import sys
from pathlib import Path

HEREDOC_START_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<cmd>(?:python3?|py)\b[^\n]*?)"
    r"<<(?P<dash>-)?[ \t]*"
    r'(?P<quote>["\']?)(?P<delim>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)[ \t]*$',
    re.MULTILINE,
)


def extract_python_heredocs(bash_text: str):
    blocks = []
    lines = bash_text.splitlines(keepends=True)
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = HEREDOC_START_RE.match(line.rstrip("\n"))
        if not m:
            i += 1
            continue
        delim = m.group("delim")
        dash = m.group("dash") is not None
        body_lines = []
        j = i + 1
        terminator_found = False
        while j < n:
            raw = lines[j]
            stripped = raw.rstrip("\n")
            candidate = stripped.strip() if dash else stripped
            if candidate == delim:
                terminator_found = True
                break
            body_lines.append(raw)
            j += 1
        if terminator_found:
            blocks.append("".join(body_lines))
            i = j + 1
        else:
            blocks.append("".join(lines[i + 1 :]))
            i = n
    return blocks


def main():
    if len(sys.argv) < 2:
        print("Usage: python bash2py.py <bash_script_path>", file=sys.stderr)
        sys.exit(1)
    input_path = Path(sys.argv[1])
    if not input_path.is_file():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    bash_text = input_path.read_text(encoding="utf-8")
    blocks = extract_python_heredocs(bash_text)
    if not blocks:
        print("No python heredocs found in the given script.", file=sys.stderr)
        sys.exit(1)
    base_name = input_path.stem
    out_dir = Path.cwd()
    written = []
    if len(blocks) == 1:
        out_path = out_dir / f"{base_name}.py"
        out_path.write_text(blocks[0], encoding="utf-8")
        written.append(out_path)
    else:
        for idx, code in enumerate(blocks, start=1):
            out_path = out_dir / f"{base_name}_{idx}.py"
            out_path.write_text(code, encoding="utf-8")
            written.append(out_path)
    for p in written:
        print(f"Wrote: {p}")


if __name__ == "__main__":
    main()
