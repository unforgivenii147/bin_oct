#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path


def samefile(path1: str, path2: str) -> bool:
    try:
        return Path(path1).samefile(path2)
    except FileNotFoundError:
        return False
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return False
