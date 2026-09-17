#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

if __name__ == "__main__":
    path = "/data/data/com.termux/files/home/.pyenv/shims:/data/data/com.termux/files/home/.pyenv/bin:/data/data/com.termux/files/home/bin:/data/data/com.termux/files/home/bashbin:/data/data/com.termux/files/home/.cargo/bin:/data/data/com.termux/files/home/.npm-global/bin:/data/data/com.termux/files/usr/lib/node_modules/.bin:/data/data/com.termux/files/usr/bin:/data/data/com.termux/files/home/.local/bin:/data/data/com.termux/files/home/sbin:/data/data/com.termux/files/home/.pyenv/bin:/data/data/com.termux/files/home/.local/share/nvim/mason/bin:/data/data/com.termux/files/usr/local/bin"
    entries = path.split(":")
    dduped = list(set(entries))
    if dduped != entries:
        print("dup found")
    print(len(entries))
    print(len(dduped))
    for k in sorted(entries):
        print(k)
    print("-" * 40)
    for k in sorted(dduped):
        print(k)
    bashrc = Path.home() / ".bashrc"
    new_path = ":".join(dduped)
    with open(bashrc, "a") as f:
        f.write(f'\nexport PATH="{new_path}"\n')
