#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

from dh import cprint, gsz


def main() -> None:
    root = Path.cwd()
    kp = {}
    files = [
        p
        for p in root.rglob("*")
        if p.is_file() and p.exists() and not p.is_symlink() and ".git" not in p.parts
    ]
    for f in files:
        path = Path(root / f)
        psz = gsz(path)
        kp.setdefault(psz, []).append(path.name)
    orig = kp
    kz = sorted(kp.keys())
    pk = {}
    for x in kz:
        pk[x] = orig.get(x)
    for k, v in pk.items():
        if len(v) > 1:
            cprint(f"{k}:", "cyan")
            for i in v:
                print(f"    - {i}")


if __name__ == "__main__":
    raise SystemExit(main())
