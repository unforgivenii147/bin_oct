#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from dh import get_files, is_binary, runcmd


def has_shell_shebang(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            first = f.readline(256).decode("utf-8", errors="ignore").strip()
        return first.startswith("#!") and ("bash" in first or "sh" in first)
    except Exception:
        return False


def process_file(path_str: str) -> tuple[bool, str]:
    path = Path(path_str)
    print(f"Formatting:  {path.name}")
    res_code, _, stderr = runcmd(["shfmt", "-w", str(path)], show_output=True)
    if res_code != 0:
        print(f"  shfmt failed on {path.name}: {stderr.strip()}", file=sys.stderr)
        return (False, path_str)
    return (True, path_str)


def main() -> None:
    cwd = Path.cwd()
    files = [
        p
        for p in get_files(cwd)
        if (not p.suffix and has_shell_shebang(p)) or p.suffix == ".sh"
    ]
    non_binary_files = [p for p in files if not is_binary(p)]
    if not non_binary_files:
        print("No shell files found to format.")
        return
    file_strings = [str(f) for f in non_binary_files]
    print(f"Processing {len(file_strings)} files...")
    with ProcessPoolExecutor() as executor:
        results = list(executor.map(process_file, file_strings))
    failed = [Path(p_str).relative_to(cwd) for success, p_str in results if not success]
    if failed:
        print("\nFailed files:")
        for f in failed:
            print(f"  - {f}")


if __name__ == "__main__":
    raise SystemExit(main())
