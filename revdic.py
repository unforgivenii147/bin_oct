#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import sys

from dh import reverse_dict

if __name__ == "__main__":
    fn = sys.argv[1]
    with open(fn, encoding="utf-8") as f:
        data = json.load(f)
    revdict = reverse_dict(data)
    with open(fn, "w", encoding="utf-8") as fo:
        json.dump(revdict, fo, ensure_ascii=False, indent=2, sort_keys=True)
    print("done")
