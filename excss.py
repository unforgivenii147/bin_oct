#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from bs4 import BeautifulSoup
from bs4.element import PageElement
from dh import cprint, get_files, get_random_filename, mpf3


def save_style(str1: list[PageElement]) -> None:
    if not str1 or len(str(str1)) < 2:
        return
    fn = "css/"
    fn += get_random_filename(10)
    fn += ".css"
    path = Path(fn)
    if path.exists():
        cprint(f"[{fn}] exists.", "red")
        path = unique_path(path)
    path.write_text("\n".join(list(str1)), encoding="utf-8")
    cprint(f"{[fn]} created.", "cyan")
    return


def process_file(path) -> bool:
    path = Path(path)
    html_content = path.read_text(encoding="utf-8")
    path = Path(path)
    soup = BeautifulSoup(html_content, "html.parser")
    styles = soup.find_all("style")
    if styles:
        cprint(f"{[path.name]} : {len(styles)} styles found.", "green")
        for style in styles:
            save_style(style.contents)
    return True


def main() -> None:
    outpath = Path("css")
    if not outpath.exists():
        outpath.mkdir(exist_ok=True)
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = (
        [Path(arg) for arg in args] if args else get_files(cwd, ext=[".html", ".htm"])
    )
    mpf3(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
