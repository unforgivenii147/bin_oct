#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import csv
import zipfile
from pathlib import Path


def is_empty_wheel(wheel_path: str) -> bool:
    print(f"checking {wheel_path}")
    try:
        with zipfile.ZipFile(wheel_path, "r") as z:
            [
                name.rstrip("/")
                for name in z.namelist()
                if name.endswith(".dist-info/")
                or (name == name.rstrip("/") + "/" and name.endswith(".dist-info"))
            ]
            dist_info = next(
                (name.rstrip("/") for name in z.namelist() if ".dist-info" in name),
                None,
            )
            if not dist_info:
                return False
            record_path = f"{dist_info}/RECORD"
            if record_path not in z.namelist():
                return False
            with z.open(record_path) as f:
                reader = csv.reader(line.decode("utf-8") for line in f)
                for row in reader:
                    if not row:
                        continue
                    path = row[0]
                    if not path.startswith(f"{dist_info}/"):
                        return False
            return True
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError):
        return False


def main() -> None:
    current_dir = Path(".")
    wheel_files = list(current_dir.glob("*.whl"))
    if not wheel_files:
        return
    empty_wheels = [str(w) for w in wheel_files if is_empty_wheel(str(w))]
    if not empty_wheels:
        print("No empty wheel files found")
        return
    print("\n".join(empty_wheels))


if __name__ == "__main__":
    raise SystemExit(main())
