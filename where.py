#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import contextlib
import shutil
import sys
import time
import traceback
from pathlib import Path

from dh import fsz
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


def parse_csv_exts(s: str | None) -> set[str] | None:
    if not s:
        return None
    parts = [p.strip().lower() for p in s.split(",") if p.strip()]
    if not parts:
        return None
    norm = set()
    for p in parts:
        if not p.startswith("."):
            p = "." + p
        norm.add(p)
    return norm


def file_matches_extensions(path: Path, allowed_exts: set[str] | None) -> bool:
    if allowed_exts is None:
        return True
    return path.suffix.lower() in allowed_exts


def file_matches_exclude(path: Path, excluded_exts: set[str] | None) -> bool:
    if excluded_exts is None:
        return False
    return path.suffix.lower() in excluded_exts


def safe_copy_file(
    src: Path, dst_root: Path, rel_path: Path, errors: list[str]
) -> None:
    try:
        dst_path = dst_root / rel_path
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst_path)
    except Exception as e:
        msg = f"[copy-error] {src} -> {dst_root / rel_path}\n{e}\n{traceback.format_exc()}"
        errors.append(msg)


class ChangeHandler(FileSystemEventHandler):
    def __init__(
        self,
        cwd: Path,
        copy_enabled: bool,
        dest_dir: Path,
        allowed_exts: set[str] | None,
        excluded_exts: set[str] | None,
        interval_sec: float,
        print_lock=None,
    ) -> None:
        super().__init__()
        self.cwd = cwd
        self.copy_enabled = copy_enabled
        self.dest_dir = dest_dir
        self.allowed_exts = allowed_exts
        self.excluded_exts = excluded_exts
        self.interval_sec = interval_sec
        self._errors: list[str] = []
        self._pending: dict[Path, str] = {}
        self._last_flush = time.time()

    def _rel(self, p: Path) -> Path:
        try:
            return p.relative_to(self.cwd)
        except ValueError:
            return Path(p.name)

    def _should_process(self, src_path: Path) -> bool:
        if (src_path.exists() and src_path.is_file()) or not src_path.exists():
            if self.allowed_exts is not None and not file_matches_extensions(
                src_path, self.allowed_exts
            ):
                return False
            return not (
                self.excluded_exts is not None
                and file_matches_exclude(src_path, self.excluded_exts)
            )
        return False

    def _queue(self, src_path: Path, reason: str) -> None:
        if not self._should_process(src_path):
            return
        if src_path.exists() and src_path.is_dir():
            return
        self._pending[src_path] = reason
        self._maybe_flush()

    def _maybe_flush(self) -> None:
        now = time.time()
        if now - self._last_flush >= self.interval_sec:
            self.flush()

    def flush(self) -> None:
        if not self._pending:
            self._last_flush = time.time()
            return
        for src_path, reason in list(self._pending.items()):
            try:
                rel_path = self._rel(src_path)
                if src_path.exists() and src_path.is_file():
                    try:
                        sz = src_path.stat().st_size
                        size_str = fsz(sz)
                    except Exception:
                        size_str = "unknown-size"
                    print(f"-  /{rel_path.as_posix()} | {reason} | {size_str}")
                    if self.copy_enabled:
                        safe_copy_file(
                            src=src_path,
                            dst_root=self.dest_dir,
                            rel_path=rel_path,
                            errors=self._errors,
                        )
                elif not src_path.exists():
                    print(f"-  /{rel_path.as_posix()} | {reason} | deleted")
                    if self.copy_enabled:
                        dst_file = self.dest_dir / rel_path
                        if dst_file.exists():
                            try:
                                dst_file.unlink()
                                print(
                                    f"  → removed from destination: /{rel_path.as_posix()}"
                                )
                            except Exception as e:
                                msg = f"[delete-error] {dst_file}\n{e}"
                                self._errors.append(msg)
            except Exception as e:
                msg = f"[processing-error] {src_path}\n{e}"
                self._errors.append(msg)
        self._pending.clear()
        self._last_flush = time.time()
        if self._errors:
            print("\n[errors] copy operation errors:")
            for msg in self._errors:
                print(msg)
            print("-" * 40)
            self._errors.clear()

    def on_created(self, event) -> None:
        if event.is_directory:
            return
        self._queue(Path(event.src_path), "create")

    def on_modified(self, event) -> None:
        if event.is_directory:
            return
        self._queue(Path(event.src_path), "change")

    def on_deleted(self, event) -> None:
        if event.is_directory:
            return
        self._queue(Path(event.src_path), "delete")

    def on_moved(self, event) -> None:
        if event.is_directory:
            return
        self._queue(Path(event.src_path), "moved-out")
        self._queue(Path(event.dest_path), "moved-in")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Watch a folder recursively, print changes, and optionally copy changed/created files."
    )
    p.add_argument(
        "folder",
        nargs="?",
        default=str(Path.cwd()),
        help="Folder to watch (default: current working directory).",
    )
    p.add_argument(
        "-c",
        "--copy",
        action="store_true",
        help="Copy changed/created files to destination.",
    )
    p.add_argument(
        "-d",
        "--dest",
        default=str(Path.home() / "tmp" / "tgz"),
        help="Destination folder for copies (default: ~/tmp/tgz).",
    )
    p.add_argument(
        "-e",
        "--extensions",
        default=None,
        help="Comma-separated allowlist of file extensions to copy, e.g. 'svg,png,txt'. If omitted, copy all changed/created file types.",
    )
    p.add_argument(
        "-x",
        "--exclude",
        default=None,
        help="Comma-separated list of file extensions to exclude from copying, e.g. 'log,tmp'.",
    )
    p.add_argument(
        "-i",
        "--interval",
        type=float,
        default=1.0,
        help="Watch interval (seconds) for batching/printing and copying (default: 1.0).",
    )
    p.add_argument(
        "--no-recursive",
        action="store_true",
        help="Disable recursive watching (watch only top-level directory).",
    )
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    cwd = Path(args.folder).expanduser().resolve()
    dest_dir = Path(args.dest).expanduser().resolve()
    if not cwd.is_dir():
        print(f"Error: folder does not exist or is not a directory: {cwd}")
        sys.exit(2)
    allowed_exts = parse_csv_exts(args.extensions)
    excluded_exts = parse_csv_exts(args.exclude)
    interval_sec = max(0.1, float(args.interval))
    if args.copy:
        dest_dir.mkdir(parents=True, exist_ok=True)
    handler = ChangeHandler(
        cwd=cwd,
        copy_enabled=bool(args.copy),
        dest_dir=dest_dir,
        allowed_exts=allowed_exts,
        excluded_exts=excluded_exts,
        interval_sec=interval_sec,
    )
    observer = Observer()
    observer.schedule(handler, str(cwd), recursive=not args.no_recursive)
    observer.start()
    print(f"Watching: {cwd}")
    if args.no_recursive:
        print("Mode: Non-recursive (top-level only)")
    else:
        print("Mode: Recursive (all subdirectories)")
    if args.copy:
        print(f"Copy enabled: destination = {dest_dir}")
    else:
        print("Copy disabled (printing only).")
    if allowed_exts is not None:
        print(f"Allowed extensions: {sorted(allowed_exts)}")
    if excluded_exts is not None:
        print(f"Excluded extensions: {sorted(excluded_exts)}")
    print(f"Interval: {interval_sec} sec (batch flush)\n")
    try:
        while True:
            time.sleep(interval_sec)
            handler.flush()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        with contextlib.suppress(Exception):
            handler.flush()
        observer.stop()
        observer.join()


if __name__ == "__main__":
    raise SystemExit(main())
