#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from pip._internal.cli.main import main as pip_main


def levenshtein_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            ins = current[j - 1] + 1
            dele = previous[j] + 1
            sub = previous[j - 1] + (ca != cb)
            current.append(min(ins, dele, sub))
        previous = current
    return previous[-1]


def levenshtein_similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    dist = levenshtein_distance(a, b)
    return 1.0 - dist / max(len(a), len(b), 1)


def partial_ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    best = 0.0
    la = len(a)
    for i in range(len(b) - la + 1):
        sub = b[i : i + la]
        sim = levenshtein_similarity(a, sub)
        if sim > best:
            best = sim
            if best == 1.0:
                break
    return best * 40


WHL_DIR = Path.cwd()
WILDCARD = "-w" in sys.argv


def install(packages: list[str]) -> int:
    args = ["install", "--user", "--no-compile", "--no-deps", *packages]
    return pip_main(args)


def pkg_name(txt: str):
    indx = txt.index("-")
    slash = txt.rfind("/")
    return txt[slash + 1 : indx]


def install_by_wildcard(pkg: str) -> None:
    whl = {pkg_name(str(p)): str(p) for p in WHL_DIR.glob("*.whl")}
    wheel_files = []
    for k, v in whl.items():
        pr = partial_ratio(pkg, k)
        if pkg in k and pr == 100:
            wheel_files.append(v)
    if not wheel_files:
        print(f"No .whl files found matching '{pkg}*'")
        return
    try:
        res = install(wheel_files)
        if not res:
            for f in wheel_files:
                print(f"  - {Path(f).name}")
                Path(f).unlink()
    except:
        return


def install_whl(pkg: str) -> None:
    whl = {pkg_name(str(p)): str(p) for p in WHL_DIR.glob("*.whl")}
    wheel_files = []
    for k, v in whl.items():
        if pkg in k:
            wheel_files.append(v)
    if not wheel_files:
        print(f"No .whl files found matching '{pkg}*'")
        return
    try:
        res = install(wheel_files)
        if not res:
            for f in wheel_files:
                print(f"  - {Path(f).name}")
                Path(f).unlink()
    except:
        return


def installwhl(pkgs):
    install(pkgs)
    for pkg in pkgs:
        p = Path(pkg)
        if p.exists():
            p.unlink()
            print(f"{p.name} removed")


if __name__ == "__main__":
    args = sys.argv[1:]
    for k in args:
        installwhl(k)
