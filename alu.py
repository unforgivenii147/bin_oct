#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

from dh import cprint, runcmd

if __name__ == "__main__":
    cmd = ["apt", "list", "--upgradable"]
    _, txt, _ = runcmd(cmd, show_output=False)
    nl = []
    target_char = "/"
    for line in txt.splitlines():
        stripped = line.strip()
        if stripped and target_char in stripped:
            indx = stripped.index(target_char)
            cleaned = stripped[:indx]
            nl.append(cleaned)
        elif stripped and "listing" not in stripped.lower():
            nl.append(stripped)
    file_name = Path("/sdcard/alu")
    if nl:
        file_name.write_text("\n".join(nl), encoding="utf-8")
        for k in nl:
            cprint(f"  - {k}")
