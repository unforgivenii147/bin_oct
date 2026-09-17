#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def read_man_file(filename: str) -> str:
    try:
        with Path(filename).open(encoding="utf-8", errors="ignore") as f:
            return f.read()
    except FileNotFoundError:
        sys.exit(f"Error: file {filename} not found")


def man_to_markdown(content: str) -> str:
    lines = content.splitlines()
    md_lines = []
    in_code_block = False
    pending_tp = None
    for line in lines:
        if line.startswith(".TH"):
            continue
        if line.startswith(".SH"):
            header = line[3:].strip()
            md_lines.append(f"# {header.title()}")
            continue
        if line.startswith(".SS"):
            subheader = line[3:].strip()
            md_lines.append(f"## {subheader.title()}")
            continue
        line = re.sub(r"\.B\s+(.+)", "**\\1**", line)
        line = re.sub(r"\.I\s+(.+)", "*\\1*", line)
        if line.startswith(".BR"):
            parts = line.split(maxsplit=1)
            if len(parts) > 1:
                tokens = parts[1].split('"')
                formatted = []
                for i, t in enumerate(tokens):
                    if not t.strip():
                        continue
                    if i % 2 == 0:
                        formatted.append(f"**{t.strip()}**")
                    else:
                        formatted.append(t.strip())
                md_lines.append(" ".join(formatted))
                continue
        if line.startswith(".IR"):
            parts = line.split(maxsplit=1)
            if len(parts) > 1:
                tokens = parts[1].split('"')
                formatted = []
                for i, t in enumerate(tokens):
                    if not t.strip():
                        continue
                    if i % 2 == 0:
                        formatted.append(f"*{t.strip()}*")
                    else:
                        formatted.append(t.strip())
                md_lines.append(" ".join(formatted))
                continue
        if line.startswith(".PP"):
            md_lines.append("")
            continue
        if line.startswith(".IP"):
            parts = line.split(maxsplit=2)
            if len(parts) >= 2 and parts[1].isdigit():
                num = parts[1]
                item = parts[2] if len(parts) > 2 else ""
                md_lines.append(f"{num}. {item}")
                continue
            if len(parts) >= 2:
                item = parts[1] if len(parts) > 1 else ""
                rest = parts[2] if len(parts) > 2 else ""
                md_lines.append(f"- {item} {rest}".strip())
                continue
        if line.startswith(".TP"):
            pending_tp = True
            continue
        if pending_tp:
            term = line.strip()
            pending_tp = False
            md_lines.append(f"- {term}:")
            continue
        if line.startswith((".nf", ".RS", ".EX")):
            if not in_code_block:
                md_lines.append("```sh")
                in_code_block = True
            continue
        if line.startswith((".fi", ".RE", ".EE")):
            if in_code_block:
                md_lines.append("```")
                in_code_block = False
            continue
        if line.startswith("."):
            continue
        if re.match(r"^\s*\$", line) or re.match(
            r"^\s*(ls|cat|grep|echo|pwd|cd|mkdir|rm|touch|man)\b", line
        ):
            if not in_code_block:
                md_lines.append("```sh")
                in_code_block = True
            md_lines.append(line)
            continue
        if in_code_block:
            md_lines.append("```")
            in_code_block = False
        line = re.sub(
            r"\b(ls|cat|grep|echo|pwd|cd|mkdir|rm|touch|man)\b", r"`\1`", line
        )
        md_lines.append(line)
    if in_code_block:
        md_lines.append("```")
    return "\n".join(md_lines)


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python man2md.py <manfile>")
        sys.exit(1)
    filename = sys.argv[1]
    raw = read_man_file(filename)
    markdown = man_to_markdown(raw)
    base, _ = os.path.splitext(filename)
    outname = base + ".md"
    Path(outname).write_text(markdown, encoding="utf-8")
    print(f"Converted {filename} → {outname}")


if __name__ == "__main__":
    raise SystemExit(main())
