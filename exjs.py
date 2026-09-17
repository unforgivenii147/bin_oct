#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from bs4 import BeautifulSoup
from bs4.element import PageElement
from dh import cprint, get_files, get_random_filename, mpf3

MAX_QUEUE = 16


def save_script(str1: list[PageElement]) -> bool:
    fn = "js/"
    fn += get_random_filename(10)
    fn += ".js"
    fn = Path(fn)
    if fn.exists():
        cprint(f"[{fn}] exists.", "red")
        return False
    if not fn.exists():
        fn.write_text("\n".join(list(str1)), encoding="utf-8")
        cprint(f"{[fn]} created.", "cyan")
    return True


def process_file(path) -> bool:
    path = Path(path)
    html_content = path.read_text(encoding="utf-8")
    path = Path(path)
    soup = BeautifulSoup(html_content, "html.parser")
    scripts = soup.find_all("script")
    if scripts:
        cprint(f"{[path.name]} : {len(scripts)} scripts found.", "magenta")
        for script in scripts:
            save_script(script.contents)
    return True


def main() -> None:
    if not Path("js").exists():
        Path("js").mkdir()
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = [Path(f) for f in args] if args else get_files(cwd, ext=[".html", "htm"])
    mpf3(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
