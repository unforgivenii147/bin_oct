#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

import pdfplumber


def process_file(path: str) -> None:
    path = Path(path)
    i = 1
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(encoding="utf-8")
            Path(path).stem
            if not Path(outdir).exists():
                Path(outdir).mkdir()
            if i < 10:
                txtfile = f"{outdir}/{Path(path).stem}00{i!s}.txt"
            elif i < 100 and i >= 10:
                txtfile = f"{outdir}/{Path(path).stem}0{i!s}.txt"
            else:
                txtfile = f"{outdir}/{Path(path).stem}{i!s}.txt"
            Path(txtfile).write_text(text, encoding="utf-8")
            print(f"{txtfile} created")
            i += 1


def main() -> None:
    process_file(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
