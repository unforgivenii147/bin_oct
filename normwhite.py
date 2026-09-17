#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from pathlib import Path


def normalize_white_space(input_path: str) -> None:
    text = Path(input_path).read_text(encoding="utf-8", errors="ignore")
    cleaned = re.sub(
        r"[\u00A0\u2000-\u200F\u2028\u2029\u202F\u205F\u3000\uFEFF]", " ", text
    )
    cleaned = re.sub(r"[\u200B-\u200D\uFEFF]", "", cleaned)
    Path(input_path).write_text(cleaned, encoding="utf-8")


if __name__ == "__main__":
    fname = sys.argv[1]
    normalize_white_space(fname)
