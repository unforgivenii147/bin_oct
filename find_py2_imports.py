#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

import tree_sitter_python as tsp
from dh import cprint, should_skip
from rapidfuzz import fuzz
from tree_sitter import Language, Parser


def get_filez(root_dir: str | Path):
    from os import walk as os_walk

    visited_dirs: set[Path] = set()
    root_dir = Path(root_dir)
    if root_dir.is_dir():
        for dirpath, dirnames, filenames in os_walk(root_dir, topdown=True):
            base_path = Path(dirpath)
            for dirname in list(dirnames):
                full_path = base_path / dirname
                resolved_path = full_path.resolve()
                if should_skip(full_path) or resolved_path in visited_dirs:
                    dirnames.remove(dirname)
                visited_dirs.add(resolved_path)
            for filename in filenames:
                path = Path(dirpath) / filename
                if not should_skip(path):
                    yield path
    else:
        yield root_dir


cwd = Path.cwd()
parser = Parser()
parser.language = Language(tsp.language())
VALID = {"import_statement", "import_from_statement"}


def process_file(path: Path) -> None:
    path = Path(path)
    src = path.read_bytes()
    tree = parser.parse(src)
    root = tree.root_node
    impoz = []
    results = [
        src[node.start_byte : node.end_byte].decode()
        for node in root.children
        if node.type in VALID
    ]
    if results:
        for k in results:
            if k.startswith("import "):
                k = k.replace("import ", "")
                if " as " in k:
                    indx = k.index(" as ")
                    k = k[:indx]
                if "." in k:
                    indx = k.index(".")
                    k = k[:indx]
                if k not in impoz and (not k.startswith("_")):
                    impoz.append(k + "\n")
            elif k.startswith("from "):
                k = k.replace("from ", "")
                if k.startswith("."):
                    continue
                if " as " in k:
                    indx = k.index(" as ")
                    k = k[:indx]
                if "." in k:
                    indx = k.index(".")
                    k = k[:indx]
                if " import" in k:
                    indx = k.index(" import")
                    k = k[:indx]
                if k not in impoz and (not k.startswith("_")):
                    impoz.append(k + "\n")
    impoz = sorted(set(impoz))
    stdlib2 = list(STDLIB2)
    for x in impoz:
        x = x.strip().lower()
        if x in STDLIB2 and x not in {"io", "os", "pathlib", "ast", "urllib"}:
            cprint(f"{path.relative_to(cwd)}", "cyan")
            continue
        for v in stdlib2:
            v = v.lower()
            ratio = fuzz.ratio(x, v)
            if (
                ratio > 85
                and len(x) > 3
                and (len(v) > 3)
                and (
                    x
                    not in {
                        "io",
                        "os",
                        "pathlib",
                        "urllib",
                        "tkinter",
                        "pickle",
                        "string",
                        "queue",
                        "urllib3",
                        "configparser",
                        "copyreg",
                        "httplib2",
                    }
                )
            ):
                cprint(f"{path.relative_to(cwd)}", "yellow")
                cprint(f"{x} / {v} / {ratio}", "green")
                continue


def main() -> None:
    for path in get_filez(cwd):
        if path.is_symlink():
            continue
        if path.suffix == ".py":
            process_file(path)


if __name__ == "__main__":
    raise SystemExit(main())
