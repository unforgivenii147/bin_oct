#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from dh import runcmd

if __name__ == "__main__":
    cmd = ["cleancss", "-O2", "removeDuplicateRules:on", "*.css", "-o", "merged.css"]
    runcmd(cmd, show_output=True)
