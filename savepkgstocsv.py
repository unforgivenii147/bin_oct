#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

OUTPUT_DIR = Path("/sdcard/backups")
TSV_FILE = OUTPUT_DIR / "installed.tsv"
CSV_FILE = OUTPUT_DIR / "installed.csv"
FIELDS = [
    "Package",
    "Version",
    "Architecture",
    "Status",
    "Priority",
    "Section",
    "Installed-Size",
    "Maintainer",
    "Homepage",
    "Description",
    "Source",
    "Essential",
    "Multi-Arch",
    "Origin",
    "Bugs",
]
FORMAT = """${binary:Package}	${Version}	${Architecture}	${Status}	${Priority}	${Section}	${Installed-Size}	${Maintainer}	${Homepage}	${binary:Summary}	${Source}	${Essential}	${Multi-Arch}	${Origin}	${Bugs}
"""


def query_packages() -> list[list[str]]:
    try:
        proc = subprocess.run(
            ["dpkg-query", "-W", f"-f={FORMAT}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        sys.exit("dpkg-query not found (not a Debian-based system)")
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.stderr.strip())
    rows = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) != len(FIELDS):
            continue
        print(cols)
        rows.append(cols)
    rows.sort(key=lambda r: int(r[6] or 0), reverse=True)
    return rows


def save_tsv(rows: list[list[str]]) -> None:
    with TSV_FILE.open("w", encoding="utf-8") as f:
        f.write("\t".join(FIELDS) + "\n")
        for row in rows:
            f.write("\t".join(row) + "\n")


def save_csv(rows: list[list[str]]) -> None:
    with CSV_FILE.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(FIELDS)
        writer.writerows(rows)


def main() -> None:
    rows = query_packages()
    save_tsv(rows)
    save_csv(rows)
    print(f"Saved {len(rows)} packages")
    print(f"TSV: {TSV_FILE}")
    print(f"CSV: {CSV_FILE}")


if __name__ == "__main__":
    raise SystemExit(main())
