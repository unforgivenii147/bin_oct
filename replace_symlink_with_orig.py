#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def process_symlink(symlink_path: Path):
    try:
        raw_target = symlink_path.readlink()
        target_path = (
            raw_target
            if raw_target.is_absolute()
            else (symlink_path.parent / raw_target).resolve()
        )
        if (
            symlink_path.parent.name == "bin"
            and target_path.parent == symlink_path.parent
        ):
            return None
        if target_path.suffix == ".so":
            return None
        if not target_path.exists():
            return {
                "status": "error",
                "msg": f"Target does not exist: {symlink_path} -> {target_path}",
            }
        symlink_path.unlink()
        if target_path.is_dir():
            shutil.copytree(target_path, symlink_path)
        else:
            shutil.copy2(target_path, symlink_path)
        return {
            "status": "replaced",
            "msg": f"Replaced: {symlink_path} -> {target_path}",
        }
    except Exception as e:
        return {"status": "error", "msg": f"Failed to process {symlink_path}: {e!s}"}


def main():
    current_dir = Path.cwd()
    replaced_log = current_dir / "replaced.txt"
    errors_log = current_dir / "errors.txt"
    print("Scanning for symlinks...")
    symlinks = [p for p in current_dir.rglob("*") if p.is_symlink()]
    if not symlinks:
        print("No symlinks found.")
        return
    print(f"Found {len(symlinks)} symlinks. Processing in parallel...")
    replaced_list = []
    errors_list = []
    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(process_symlink, symlink): symlink for symlink in symlinks
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                if result["status"] == "replaced":
                    replaced_list.append(result["msg"])
                elif result["status"] == "error":
                    errors_list.append(result["msg"])
    if replaced_list:
        replaced_log.write_text("\n".join(replaced_list) + "\n", encoding="utf-8")
        print(
            f"Successfully replaced {len(replaced_list)} symlinks. Logged to replaced.txt"
        )
    if errors_list:
        errors_log.write_text("\n".join(errors_list) + "\n", encoding="utf-8")
        print(f"Encountered {len(errors_list)} errors. Logged to errors.txt")


if __name__ == "__main__":
    raise SystemExit(main())
