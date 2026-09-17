#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from pathlib import Path

from dh import get_nobinary

IF_BLOCK_REGEX = re.compile(
    "^if\\s+\\[\\s*\\$\\((\\S+)\\)\\s*\\{\\-ne\\s+0\\s*\\}\\]\\s*;\\s*then\\s*\\n((?:.|\\n)*?)^\\s*exit\\s+1\\s*$(.*?)^\\s*fi",
    re.MULTILINE | re.IGNORECASE,
)


def remove_conditional_exit_blocks(path: Path) -> None:
    try:
        original_content = path.read_text(encoding="utf-8")
        modified_content = original_content
        while True:
            match = IF_BLOCK_REGEX.search(modified_content)
            if not match:
                break
            modified_content = (
                modified_content[: match.start()] + modified_content[match.end() :]
            )
        if original_content != modified_content:
            path.write_text(modified_content, encoding="utf-8")
            print(f"Cleaned: {path}")
    except Exception as e:
        print(f"Error processing {path}: {e}", file=sys.stderr)


def main() -> None:
    cwd = Path.cwd()
    files_to_process = get_nobinary(cwd)
    for item_path in files_to_process:
        if item_path.is_file():
            try:
                content = item_path.read_text(encoding="utf-8", errors="ignore")
                is_likely_bash = False
                if content.startswith(("#!/bin/bash", "#!/usr/bin/env bash")) or oct(
                    item_path.stat().st_mode
                )[-3:] not in (
                    "000",
                    "001",
                    "010",
                    "011",
                    "002",
                    "012",
                    "100",
                    "110",
                    "111",
                    "101",
                ):
                    is_likely_bash = True
                if is_likely_bash:
                    remove_conditional_exit_blocks(item_path)
            except Exception as e:
                print(f"Could not read or process {item_path}: {e}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
