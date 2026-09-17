#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from pathlib import Path

from dh import get_removed_lines, read_lines

INPLACE = "-w" in sys.argv
if __name__ == "__main__":
    fn = Path(sys.argv[1])
    content = fn.read_text(encoding="utf-8")
    lines = read_lines(fn, ke=False)
    nl = []
    for line in lines:
        if "<:" in line or ">:" in line:
            continue
        text = re.sub("<[^>]*>", "", line)
        nl.append(text)
    new_content = "\n".join(nl)
    removed, _added = get_removed_lines(content, new_content)
    for k in removed:
        print(f" - {k}")
    if INPLACE:
        fn.write_text(new_content, encoding="utf8")
    print("file didnt updated.\n for update inplace rerun with -w arg")
