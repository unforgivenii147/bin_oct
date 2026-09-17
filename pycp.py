#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import sys
from pathlib import Path

src = Path(sys.argv[1].strip())
dest = Path("/data/data/com.termux/files/usr")
shutil.copy2(str(src), dest)
print("done")
