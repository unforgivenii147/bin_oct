#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import cprint, get_files

TIMEOUT = 0


def get_files(folder: Path) -> list[Path]:
    return [
        p
        for p in folder.rglob("*")
        if p.is_file() and not p.is_symlink() and ".git" not in p.parts
    ]


def wait_for_keypress(timeout: int) -> bool:
    if timeout <= 0:
        return False
    import select

    sys.stdout.flush()
    r, _, _ = select.select([sys.stdin], [], [], timeout)
    if r:
        sys.stdin.readline()
        return True
    return False


def main() -> int:
    cwd = Path.cwd()
    files = get_files(cwd)
    empty_files = [
        p for p in files if p.stat().st_size == 0 and p.name != "__init__.py"
    ]
    found = len(empty_files)
    if not found:
        cprint("no empty files found", "cyan")
        sys.exit(0)
    cprint(f"{found} empty files found.", "cyan")
    for empty_file in empty_files:
        cprint(f"    - {empty_file.relative_to(cwd)}", "yellow")
    cprint(f"Press any key within {TIMEOUT} seconds to abort.", "magenta")
    if wait_for_keypress(TIMEOUT):
        cprint("Aborted by user.", "red")
        return 1
    deleted = 0
    failed = 0
    for empty_file in empty_files:
        try:
            if empty_file.exists():
                empty_file.unlink()
                deleted += 1
        except Exception as e:
            failed += 1
            cprint(f"Failed to remove {empty_file}: {e}", "red")
    cprint(f"Deleted: {deleted}, Failed: {failed}", "green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
