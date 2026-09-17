#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

if __name__ == "__main__":
    fn = Path(sys.argv[1])
    outf = fn.with_suffix(".json")
    data: bytes
    with open(fn, "rb") as f:
        data = pickle.load(f)
        with open(outf, "w") as fo:
            json.dump(data, fo, ensure_ascii=False, indent=2)
