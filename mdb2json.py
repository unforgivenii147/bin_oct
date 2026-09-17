#!/data/data/com.termux/files/home/.local/bin/python
"""
MDB to JSON Converter
Converts Microsoft Access database files (.mdb/.accdb) to JSON format.

Features:
- Parallel processing with configurable workers
- Recursive directory scanning
- Streaming JSON output for memory efficiency
- Robust error handling and logging
- Handles multiple input files/directories
"""

import argparse
import json
import sys
import traceback
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

from loguru import logger

try:
    import pyodbc
except ImportError:
    print(
        "ERROR: pyodbc is required. Install with: pip install pyodbc", file=sys.stderr
    )
    sys.exit(1)


DEFAULT_WORKERS = 8
MDB_EXTENSIONS = {".mdb", ".accdb"}
BATCH_SIZE = 1000  # rows per batch when streaming
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(processName)s: %(message)s"


# ---------- Logging setup ----------


def _convert_value(value: Any) -> Any:
    """Convert database values to JSON-serializable types."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        # Preserve precision when possible, else fall back to float
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        # Encode binary as base64-ish hex string (safe for JSON)
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()
    if isinstance(value, (list, tuple)):
        return [_convert_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _convert_value(v) for k, v in value.items()}
    # Last resort: stringify
    return str(value)


def _build_dsn(mdb_path: Path) -> str:
    """
    Build an ODBC connection string for the given MDB/ACCDB file.
    Uses the Microsoft Access Driver. Works on Windows with Access Database Engine
    installed. On Linux, requires mdbtools ODBC driver.
    """
    # Try modern driver first, then fall back to older ones.
    drivers = [
        "Microsoft Access Driver (*.mdb, *.accdb)",
        "Microsoft Access Driver (*.mdb)",
        "MDBTools",
    ]
    # We return a "drivers to try" list via the connection function, not here.
    # This helper just returns the absolute path string.
    return str(mdb_path.resolve())


def _connect(mdb_path: Path) -> "pyodbc.Connection":
    """Attempt to connect using a series of known drivers."""
    abs_path = str(mdb_path.resolve())
    candidate_drivers = [
        "Microsoft Access Driver (*.mdb, *.accdb)",
        "Microsoft Access Driver (*.mdb)",
        "MDBTools",
    ]
    last_err: Exception | None = None
    for drv in candidate_drivers:
        try:
            conn_str = f"DRIVER={{{drv}}};DBQ={abs_path};"
            return pyodbc.connect(conn_str, autocommit=True, timeout=30)
        except pyodbc.Error as exc:
            last_err = exc
            continue
    raise RuntimeError(
        f"Could not connect to {mdb_path} with any known ODBC driver. "
        f"Last error: {last_err}"
    )


# ---------- Core conversion (worker function) ----------


def convert_mdb_to_json(
    mdb_path: str,
    output_path: str | None = None,
    overwrite: bool = False,
    pretty: bool = False,
    tables: list[str] | None = None,
) -> tuple[str, bool, str]:
    """
    Convert a single MDB file to JSON.

    Returns:
        (input_path, success, message)
    """
    src = Path(mdb_path)
    try:
        if not src.is_file():
            return (str(src), False, "Not a file")

        dst = Path(output_path) if output_path else src.with_suffix(".json")

        if dst.exists() and not overwrite:
            return (str(src), False, f"Output exists (use --overwrite): {dst}")

        dst.parent.mkdir(parents=True, exist_ok=True)

        conn = _connect(src)
        try:
            cursor = conn.cursor()

            # Discover tables
            all_tables: list[str] = []
            for row in cursor.tables(tableType="TABLE"):
                name = row.table_name
                if name and not name.startswith("MSys"):
                    all_tables.append(name)

            if tables:
                # Keep only requested tables that exist
                requested = {t.lower() for t in tables}
                all_tables = [t for t in all_tables if t.lower() in requested]

            # Write JSON streaming per table
            indent = 2 if pretty else None
            with dst.open("w", encoding="utf-8") as fh:
                fh.write("{\n")
                fh.write(f'  "_source": {json.dumps(str(src))},\n')
                fh.write(
                    f'  "_converted_at": {json.dumps(datetime.utcnow().isoformat() + "Z")},\n'
                )
                fh.write('  "tables": {\n')

                for t_idx, table in enumerate(all_tables):
                    try:
                        # Quote identifier with brackets (Access style)
                        safe_table = table.replace("]", "]]")
                        cursor.execute(f"SELECT * FROM [{safe_table}]")

                        fh.write(f"    {json.dumps(table)}: [\n")
                        cols = (
                            [d[0] for d in cursor.description]
                            if cursor.description
                            else []
                        )

                        first = True
                        while True:
                            rows = cursor.fetchmany(BATCH_SIZE)
                            if not rows:
                                break
                            for row in rows:
                                record = {
                                    cols[i]: _convert_value(row[i])
                                    for i in range(len(cols))
                                }
                                if not first:
                                    fh.write(",\n")
                                else:
                                    first = False
                                # Compact per-row dump for memory/perf balance
                                fh.write("      ")
                                fh.write(
                                    json.dumps(record, ensure_ascii=False, default=str)
                                )
                        fh.write("\n    ]")
                    except Exception as tbl_err:  # noqa: BLE001
                        logger.warning("Table %s in %s failed: %s", table, src, tbl_err)
                        fh.write(
                            f'    {json.dumps(table)}: {{"_error": '
                            f"{json.dumps(str(tbl_err))}}}"
                        )

                    if t_idx < len(all_tables) - 1:
                        fh.write(",\n")
                    else:
                        fh.write("\n")

                fh.write("  }\n}\n")

            size_kb = dst.stat().st_size / 1024
            return (str(src), True, f"Wrote {dst} ({size_kb:.1f} KB)")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    except Exception as exc:  # noqa: BLE001
        tb = traceback.format_exc(limit=3)
        logger.debug("Failure on %s:\n%s", src, tb)
        return (str(src), False, f"{type(exc).__name__}: {exc}")


# ---------- Discovery ----------


def discover_mdb_files(inputs: Iterable[str]) -> list[Path]:
    """Resolve inputs (files or dirs) into a list of MDB/ACCDB paths."""
    found: list[Path] = []
    seen = set()

    def add(p: Path) -> None:
        try:
            rp = p.resolve()
        except OSError:
            return
        if rp in seen:
            return
        seen.add(rp)
        found.append(rp)

    for raw in inputs:
        p = Path(raw).expanduser()
        if p.is_file():
            if p.suffix.lower() in MDB_EXTENSIONS:
                add(p)
            else:
                logger.warning("Skipping non-MDB file: %s", p)
        elif p.is_dir():
            for ext in MDB_EXTENSIONS:
                for f in p.rglob(f"*{ext}"):
                    if f.is_file():
                        add(f)
                # case-insensitive on case-sensitive filesystems
                for f in p.rglob(f"*{ext.upper()}"):
                    if f.is_file():
                        add(f)
        else:
            logger.warning("Path does not exist: %s", p)

    return found


# ---------- Main ----------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert Microsoft Access .mdb/.accdb files to JSON.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Files or directories to process. If omitted, scans CWD recursively.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        help="Directory to write JSON files into. Defaults to alongside each source.",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Number of parallel worker processes.",
    )
    parser.add_argument(
        "-f",
        "--overwrite",
        action="store_true",
        help="Overwrite existing JSON output files.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON (larger files, slower).",
    )
    parser.add_argument(
        "-t",
        "--tables",
        nargs="+",
        help="Only convert the specified tables (case-insensitive).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    inputs = args.inputs if args.inputs else ["."]
    files = discover_mdb_files(inputs)

    if not files:
        logger.error("No .mdb/.accdb files found in: %s", inputs)
        return 2

    print("Found %d MDB file(s). Using %d workers.", len(files), args.workers)

    # Build per-file output paths up-front (deterministic)
    jobs: list[tuple[str, str | None]] = []
    for f in files:
        if args.output_dir:
            out_dir = Path(args.output_dir).expanduser().resolve()
            out_path = str(out_dir / (f.stem + ".json"))
        else:
            out_path = None  # alongside source
        jobs.append((str(f), out_path))

    # Use ProcessPoolExecutor with imap_unordered semantics via submit+as_completed,
    # or map_unordered equivalent. We use submit + as_completed for clarity and
    # to allow different output paths per job.
    successes = 0
    failures = 0
    total = len(jobs)
    done = 0

    try:
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
            future_map = {
                pool.submit(
                    convert_mdb_to_json,
                    src,
                    dst,
                    args.overwrite,
                    args.pretty,
                    args.tables,
                ): src
                for src, dst in jobs
            }

            for fut in as_completed(future_map):
                src = future_map[fut]
                done += 1
                try:
                    _, ok, msg = fut.result()
                except Exception as exc:  # noqa: BLE001
                    ok, msg = False, f"Unhandled: {exc}"
                if ok:
                    successes += 1
                    print("[%d/%d] OK   %s — %s", done, total, src, msg)
                else:
                    failures += 1
                    logger.error("[%d/%d] FAIL %s — %s", done, total, src, msg)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        return 130

    print("Done. Successes: %d, Failures: %d, Total: %d", successes, failures, total)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
