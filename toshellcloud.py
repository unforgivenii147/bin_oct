#!/usr/bin/env python
from __future__ import annotations

import sys
from multiprocessing import Pool
from pathlib import Path


def convert_shebang(path: Path) -> tuple[str, bool, str | None]:
    try:
        content = path.read_text(encoding="utf-8")
        if not content.startswith("#!"):
            return str(path), False, "No shebang found"
        lines = content.split("\n")
        shebang = lines[0]
        termux_patterns = [
            "#!/data/data/com.termux/files/usr/bin/python",
            "#!/data/data/com.termux/files/usr/bin/python3",
            "#!/data/data/com.termux/files/usr/bin/env python",
            "#!/data/data/com.termux/files/usr/bin/env python3",
        ]
        if shebang not in termux_patterns:
            return str(path), False, "Not a Termux shebang"
        if "python3" in shebang:
            new_shebang = "#!/usr/bin/env python3"
        else:
            new_shebang = "#!/usr/bin/env python"
        lines[0] = new_shebang
        new_content = "\n".join(lines)
        path.write_text(new_content, encoding="utf-8")
        return str(path), True, None
    except Exception as e:
        return str(path), False, str(e)


def find_py_files(directory: Path) -> list:
    return list(directory.rglob("*.py"))


def main():
    if len(sys.argv) > 1:
        target_dir = Path(sys.argv[1])
    else:
        target_dir = Path(".")
    if not target_dir.exists() or not target_dir.is_dir():
        print(f"Error: {target_dir} is not a valid directory")
        sys.exit(1)
    print(f"Searching for Python files in: {target_dir.absolute()}")
    py_files = find_py_files(target_dir)
    if not py_files:
        print("No Python files found.")
        return
    print(f"Found {len(py_files)} Python files")
    print("Converting Termux shebangs...")
    print("-" * 40)
    with Pool(processes=8) as pool:
        results = pool.starmap(convert_shebang, [(f,) for f in py_files])
    successful = 0
    skipped = 0
    failed = 0
    print("\nResults:")
    print("-" * 40)
    for path, success, error in results:
        if success:
            successful += 1
            print(f"✅ {path}")
        elif error == "No shebang found" or error == "Not a Termux shebang":
            skipped += 1
            print(f"⏭️  {path} - {error}")
        else:
            failed += 1
            print(f"❌ {path} - {error}")
    print("-" * 40)
    print(f"\nSummary:")
    print(f"  Successfully converted: {successful}")
    print(f"  Skipped: {skipped}")
    print(f"  Failed: {failed}")
    print(f"  Total files processed: {len(py_files)}")


if __name__ == "__main__":
    main()
