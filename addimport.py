#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from fastwalk import walk_files

shebang = "#!/data/data/com.termux/files/usr/bin/python\n"


def process_file(fp, module_name):
    if not fp.exists() or fp.is_symlink():
        return
    print(f"processing {fp}")
    data = []
    newdata = []
    with Path(fp).open(encoding="utf-8") as fin:
        data = fin.readlines()
    if data[0].startswith("#!"):
        newdata.extend((data[0], f"import {module_name}"))
        for k in data[1:]:
            newdata.append(k)
    else:
        newdata.extend((shebang, "import regex as re\nimport os\n"))
        for k in data:
            newdata.append(k)
    with Path(fp).open("w", encoding="utf-8") as fo:
        fo.writelines(newdata)
    return


def main():
    cwd = Path.cwd()
    files = []
    cwd = Path.cwd()
    modname = sys.argv[1]
    for pth in walk_files(cwd):
        path = Path(pth)
        if path.is_file() and path.suffix == ".py":
            files.append(path)
    for f in files:
        process_file(f, modname)


if __name__ == "__main__":
    raise SystemExit(main())
