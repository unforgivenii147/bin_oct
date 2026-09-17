#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import site
from pathlib import Path

u = Path(site.getusersitepackages())
for p in u.iterdir():
    if p.is_dir() and not p.name.endswith((".dist-info", ".egg-info")):
        has_entry = False
        for pattern in [f"{p.name}*.dist-info", f"{p.name}*.egg-info"]:
            for d in u.glob(pattern):
                if (d / "entry_points.txt").exists():
                    has_entry = True
                    break
            if has_entry:
                break
        if not has_entry:
            print(p.name)
