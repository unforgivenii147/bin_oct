#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import site
from pathlib import Path

user_site = Path(site.getusersitepackages())
extensions = {".so", ".pyd", ".dylib", ".dll"}
for pkg in user_site.iterdir():
    if pkg.is_dir() and not pkg.name.endswith((".dist-info", ".egg-info")):
        has_compiled = False
        for _root, _dirs, files in os.walk(pkg):
            for f in files:
                if os.path.splitext(f)[1].lower() in extensions:
                    has_compiled = True
                    break
            if has_compiled:
                break
        if has_compiled:
            print(pkg.name)
