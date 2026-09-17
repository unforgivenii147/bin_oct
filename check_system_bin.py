#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


def calculate_hash(path: Path, chunk_size=8192):
    sha256 = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except (OSError, PermissionError):
        return None


def get_system_bin_hashes():
    system_bin = Path("/system/bin")
    if not system_bin.exists():
        print("⚠️  /system/bin directory not found!")
        return {}
    hashes = {}
    print("📂 Scanning /system/bin files...")
    for path in system_bin.iterdir():
        try:
            if path.is_file() or path.is_symlink():
                hash_value = calculate_hash(path)
                if hash_value:
                    hashes[hash_value] = path.name
        except (PermissionError, OSError):
            continue
    print(f"✅ Scanned {len(hashes)} files in /system/bin\n")
    return hashes


def check_and_move_files(system_hashes):
    current_dir = Path.cwd()
    matches_dir = current_dir / "matched_system_files"
    matches_dir.mkdir(exist_ok=True)
    matches = []
    moved = []
    print("🔍 Scanning current directory...")
    for path in current_dir.iterdir():
        try:
            if path.is_file() and (not path.name.startswith(".")):
                if path.resolve() == matches_dir.resolve():
                    continue
                hash_value = calculate_hash(path)
                if hash_value and hash_value in system_hashes:
                    system_filename = system_hashes[hash_value]
                    matches.append((path.name, system_filename))
                    if path.name == system_filename:
                        dest_path = matches_dir / path.name
                        counter = 1
                        original_dest = dest_path
                        while dest_path.exists():
                            dest_path = (
                                original_dest.parent
                                / f"{original_dest.stem}_{counter}{original_dest.suffix}"
                            )
                            counter += 1
                        shutil.move(path, dest_path)
                        moved.append((path.name, dest_path.name))
                        print(f"  📦 Moved: {path.name} -> {dest_path.name}")
                    else:
                        print(
                            f"  ⚠️  Hash matches but filename differs: {path.name} (system: {system_filename})"
                        )
        except (PermissionError, OSError) as e:
            print(f"  ⚠️  Error with {path.name}: {e}")
            continue
    return (matches, moved)


def main():
    print("-" * 40)
    print("🔐 File Hash Comparison & Move Tool")
    print("-" * 40)
    system_hashes = get_system_bin_hashes()
    if not system_hashes:
        print("❌ No readable files found in /system/bin")
        return
    matches, moved = check_and_move_files(system_hashes)
    print("\n" + "=" * 40)
    print("📊 SUMMARY")
    print("-" * 40)
    if matches:
        print(f"⚠️  Found {len(matches)} files with matching hashes:")
        for local_file, system_file in matches:
            status = "✅ MOVED" if local_file == system_file else "❌ Name mismatch"
            print(f"  • {local_file} matches /system/bin/{system_file} - {status}")
        if moved:
            print(
                f"\n📦 Moved {len(moved)} files to './matched_system_files/' directory:"
            )
            for original, new_name in moved:
                print(f"  • {original} -> {new_name}")
    else:
        print("✅ No matching files found.")
    print("-" * 40)


if __name__ == "__main__":
    raise SystemExit(main())
