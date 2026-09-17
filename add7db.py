#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import base64
import io
import os
import sqlite3
import sys
from pathlib import Path
from sqlite3 import Cursor

import py7zr


def get_current_folder_name() -> str:
    return Path(Path.cwd()).name


def get_user_folder_name(default_name: str):
    while True:
        user_input = input(f"Enter folder name (default: {default_name}): ").strip()
        if not user_input:
            return default_name
        return user_input


def folder_exists_in_db(cursor: Cursor, folder_name):
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (folder_name,)
    )
    return cursor.fetchone() is not None


def create_folder_table(cursor: Cursor, folder_name) -> None:
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS "{folder_name}" (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            file_contents BLOB,
            compressed BOOLEAN DEFAULT 0,
            original_size INTEGER DEFAULT 0,
            compressed_size INTEGER DEFAULT 0
        )
    """)


def compress_data(data_bytes) -> str | None:
    if not data_bytes:
        return None
    try:
        buffer = io.BytesIO()
        with py7zr.SevenZipFile(buffer, "w") as archive:
            archive.writestr("content", data_bytes)
        compressed_data = buffer.getvalue()
        return base64.b64encode(compressed_data).decode("ascii")
    except Exception as e:
        print(f"    Compression error: {e!s}")
        return None


def read_file_contents(path: str):
    try:
        encodings = ["utf-8", "latin-1", "cp1252", "iso-8859-1"]
        get_size = Path(path).stat().st_size
        if get_size > 10 * 1024 * 1024:
            print(
                f"    Warning: Large file ({get_size / 1024 / 1024:.1f}MB), may take time to compress"
            )
        for encoding in encodings:
            try:
                with Path(path).open(encoding=encoding) as f:
                    content = f.read()
                    return {
                        "content": content,
                        "is_binary": False,
                        "original_size": len(content.encode("utf-8", errors="replace")),
                    }
            except (UnicodeDecodeError, UnicodeError):
                continue
        with Path(path).open("rb") as f:
            content = f.read()
            return {
                "content": content,
                "is_binary": True,
                "original_size": len(content),
            }
    except PermissionError:
        return {
            "content": error_msg,
            "is_binary": False,
            "original_size": len(error_msg),
        }
    except Exception:
        return {
            "content": error_msg,
            "is_binary": False,
            "original_size": len(error_msg),
        }


def get_files_in_cwd():
    cwd = Path.cwd()
    files = []
    try:
        for item_path in sorted(cwd.iterdir()):
            if item_path.is_file():
                get_size = item_path.stat().st_size
                size_str = (
                    f"{get_size / 1024:.1f}KB"
                    if get_size < 1024 * 1024
                    else f"{get_size / 1024 / 1024:.1f}MB"
                )
                print(f"  Processing: {item_path.name} ({size_str})")
                file_data = read_file_contents(str(item_path))
                if file_data["is_binary"]:
                    compressed = compress_data(file_data["content"])
                    if compressed:
                        files.append(
                            {
                                "filename": item_path.name,
                                "contents": compressed,
                                "compressed": 1,
                                "original_size": file_data["original_size"],
                                "compressed_size": len(compressed),
                            }
                        )
                        print(
                            f"    ✓ Compressed {
                                file_data['original_size'] / 1024:.1f}KB to {
                                len(compressed) / 1024:.1f}KB"
                        )
                    else:
                        files.append(
                            {
                                "filename": item_path.name,
                                "contents": "[Binary file - compression failed]",
                                "compressed": 0,
                                "original_size": file_data["original_size"],
                                "compressed_size": 0,
                            }
                        )
                else:
                    files.append(
                        {
                            "filename": item_path.name,
                            "contents": file_data["content"],
                            "compressed": 0,
                            "original_size": file_data["original_size"],
                            "compressed_size": 0,
                        }
                    )
                    print(
                        f"    ✓ Stored as text ({file_data['original_size'] / 1024:.1f}KB)"
                    )
    except PermissionError:
        print("Warning: Permission denied accessing some files")
    return files


def insert_files(cursor: Cursor, folder_name, files) -> None:
    for file_info in files:
        cursor.execute(
            f"""
            INSERT INTO "{folder_name}" (filename, file_contents, compressed, original_size, compressed_size)
            VALUES (?, ?, ?, ?, ?)
        """,
            (
                file_info["filename"],
                file_info["contents"],
                file_info.get("compressed", 0),
                file_info.get("original_size", 0),
                file_info.get("compressed_size", 0),
            ),
        )


def main() -> None:
    try:
        pass
    except ImportError:
        print("Error: py7zr library is not installed.")
        print("Install it with: pip install py7zr")
        sys.exit(1)
    db_path = "/sdcard/pkgs.db"
    if not os.access("/sdcard/", os.W_OK):
        print("Error: Cannot write to /sdcard/. Make sure you have proper permissions.")
        print("On Android, you might need to:")
        print("1. Grant storage permissions to Termux/terminal app")
        print("2. Or run the script with appropriate permissions")
        sys.exit(1)
    default_name = get_current_folder_name()
    folder_name = get_user_folder_name(default_name)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    while folder_exists_in_db(cursor, folder_name):
        print(f"Folder name '{folder_name}' already exists in database!")
        folder_name = input("Please enter a different name: ").strip()
        if not folder_name:
            folder_name = default_name + "_new"
            print(f"Using '{folder_name}' as default")
    create_folder_table(cursor, folder_name)
    print(f"\nScanning current directory: {Path.cwd()}")
    print("Reading and compressing file contents...")
    files = get_files_in_cwd()
    if not files:
        print("No files found in current directory!")
    else:
        insert_files(cursor, folder_name, files)
        conn.commit()
        total_original = sum(f.get("original_size", 0) for f in files)
        total_compressed = sum(f.get("compressed_size", 0) for f in files)
        print(f"\n✅ Successfully added {len(files)} files to table '{folder_name}'")
        if total_compressed > 0:
            ratio = (
                (1 - total_compressed / total_original) * 40
                if total_original > 0
                else 0
            )
            print("📊 Storage stats:")
            print(f"   Original size: {total_original / 1024 / 1024:.2f}MB")
            print(f"   Compressed size: {total_compressed / 1024 / 1024:.2f}MB")
            print(f"   Compression ratio: {ratio:.1f}% saved")
        else:
            print(f"   Total size: {total_original / 1024 / 1024:.2f}MB")
    conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
