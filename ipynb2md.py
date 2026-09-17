#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

import nbformat

if __name__ == "__main__":
    fn = Path(sys.argv[1])
    with Path(fn).open(encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)
    fo = fn.with_suffix(".md")
    with Path(fo).open("w", encoding="utf-8") as out:
        for _i, cell in enumerate(nb.cells, 1):
            out.write("\n")
            if cell.cell_type == "markdown":
                out.write(cell.source + "\n\n")
            elif cell.cell_type == "code":
                out.write("```python\n")
                out.write(cell.source + "\n")
                out.write("```\n\n")
    print(f"Exported → {fo}")
