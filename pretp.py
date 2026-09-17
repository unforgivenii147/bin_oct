#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import concurrent.futures
import subprocess
from pathlib import Path

from tqdm import tqdm


def format_file(path: str) -> str | None:
    try:
        subprocess.run(
            ["npx", "prettier", "--write", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
        return None
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        return f"{path}: {(e.stderr if hasattr(e, 'stderr') else str(e))}"


def main() -> None:
    target_extensions = (
        ".js",
        ".css",
        ".htm",
        ".html",
        ".ts",
        ".jsx",
        ".tsx",
        ".xml",
        ".json",
    )
    exclude_dirs = {".git"}
    exclude_extensions = (".min.js", ".min.css")
    files_to_format = []
    print("Scanning directory for files...")
    base_path = Path(".")
    for path in base_path.rglob("*"):
        if not path.is_file():
            continue
        if any(part in exclude_dirs for part in path.parts):
            continue
        if (
            (
                path.suffix in target_extensions
                or any(path.name.endswith(ext) for ext in target_extensions)
            )
            and any(path.name.endswith(ext) for ext in target_extensions)
            and (not any(path.name.endswith(ext) for ext in exclude_extensions))
        ):
            files_to_format.append(str(path))
    if not files_to_format:
        print("No matching files found.")
        return
    errors = []
    with (
        tqdm(total=len(files_to_format), desc="Beautifying", unit="file") as pbar,
        concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor,
    ):
        future_to_file = {executor.submit(format_file, f): f for f in files_to_format}
        for future in concurrent.futures.as_completed(future_to_file):
            err = future.result()
            if err:
                errors.append(err)
            pbar.update(1)
    print("\n" + "=" * 30)
    print(f"Finished processing {len(files_to_format)} files.")
    if errors:
        print(f"Encountered {len(errors)} errors:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("All files formatted successfully!")


if __name__ == "__main__":
    raise SystemExit(main())
