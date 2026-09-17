#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

ALLOWED_DIST_INFO_FILES = {
    "METADATA",
    "RECORD",
    "WHEEL",
    "entry_points.txt",
    "top_level.txt",
}


def clean_records():
    for dist_info in Path(".").glob("*.dist-info"):
        record_file = dist_info / "RECORD"
        if record_file.exists():
            lines = record_file.read_text().splitlines()
            filtered = []
            for line in lines:
                if not line.strip():
                    continue
                parts = line.split(",")
                path = parts[0]
                path_obj = Path(path)
                is_in_dist_info = any(
                    part.endswith(".dist-info") for part in path_obj.parts
                )
                if is_in_dist_info and path_obj.name not in ALLOWED_DIST_INFO_FILES:
                    print(f"Removed dist-info reference: {path}")
                    continue
                filtered.append(line)
            record_file.write_text("\n".join(filtered) + ("\n" if filtered else ""))
            print(f"record file in {record_file.parent.name} cleaned.")


def main():
    clean_records()


if __name__ == "__main__":
    raise SystemExit(main())
