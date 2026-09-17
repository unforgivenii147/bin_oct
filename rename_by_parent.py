#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
from os.path import dirname as dirn, isfile as isf, join as jn
from pathlib import Path


class DirectoryWalker:
    def __init__(self, directory) -> None:
        self.stack = [directory]
        self.files = []
        self.index = 0

    def __getitem__(self, index):
        while 1:
            try:
                file = self.files[self.index]
                self.index = self.index + 1
            except IndexError:
                self.directory = self.stack.pop()
                self.files = os.listdir(self.directory)
                self.index = 0
            else:
                fullname = jn(self.directory, file)
                if os.path.isdir(fullname) and not os.path.islink(fullname):
                    self.stack.append(fullname)
                return fullname
        return None


if __name__ == "__main__":
    cwd = Path.cwd()
    for file in DirectoryWalker(str(cwd)):
        if isf(file) and file.endswith("README.pdf"):
            dirname1 = dirn(file)
            full_name = file
            dirs = dirname1.split("/")
            last_dir = dirs[len(dirs) - 1]
            new_name = last_dir + ".pdf"
            if not os.path.exists(new_name):
                try:
                    os.rename(file, jn(dirname1, new_name))
                    print(f"file {full_name} renamed to {new_name}")
                except OSError as e:
                    print(e)
