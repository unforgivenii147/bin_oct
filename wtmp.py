#!/data/data/com.termux/files/home/.local/bin/python
import os
import pathlib
import shutil
import sys
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

DEST_DIR = pathlib.Path("~/tmp/tgz").expanduser()
ALLOWED_EXTENSIONS = (
    ".tar.gz",
    ".whl",
    ".tar.xz",
    ".zip",
    ".tar.bz2",
)


def copy_if_match(src_path) -> None:
    if src_path.endswith(ALLOWED_EXTENSIONS):
        try:
            pathlib.Path(DEST_DIR).mkdir(exist_ok=True, parents=True)
            dest = os.path.join(
                DEST_DIR,
                pathlib.Path(src_path).name,
            )
            shutil.copy2(src_path, dest)
            print(src_path)
        except Exception as e:
            print(f"Failed to copy {src_path}: {e}")


def startup_scan(fpath: str) -> None:
    for root, _dirs, files in os.walk(fpath):
        for f in files:
            full_path = os.path.join(root, f)
            copy_if_match(full_path)


class CopyEventHandler(FileSystemEventHandler):
    def on_created(self, event) -> None:
        if not event.is_directory:
            copy_if_match(event.src_path)

    def on_modified(self, event) -> None:
        if not event.is_directory:
            copy_if_match(event.src_path)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "/data/data/com.termux/files/usr/tmp"
    startup_scan(path)
    event_handler = CopyEventHandler()
    observer = Observer()
    observer.schedule(event_handler, path, recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
