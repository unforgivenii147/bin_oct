#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import site
from pathlib import Path

u = Path(site.getusersitepackages())
nl = []
for p in u.iterdir():
    if p.is_dir() and (not p.name.endswith((".dist-info", ".egg-info"))):
        for d in u.glob(f"{p.name}*.dist-info"):
            if (d / "entry_points.txt").exists():
                print(p.name)
                nl.append(p.name)
                break
        else:
            for d in u.glob(f"{p.name}*.egg-info"):
                if (d / "entry_points.txt").exists():
                    print(p.name)
                    nl.append(d.name)
                    break
outfile = Path("/sdcard/data/pkgs_with_scripts")
content = "\n".join(nl)
outfile.write_text(content, encoding="utf-8")
